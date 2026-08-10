"""What the panel actually shows: assertions over rendered Liquid output.

Every defect that has reached the physical device came from this layer, and
none of them was visible to a Python test:

1. A leftover ``{% assign word = nil %}`` survived a botched string replace,
   so every card rendered as "Vocabulary unavailable".
2. A deck picker written in Liquid froze the screen, because TRMNL skips a
   render when the polled payload is byte-identical to the last one.
3. The landing page shipped a string-concatenation fragment as visible prose
   (covered separately in ``test_site_builder.py``).
4. The title bar's level strip showed all five bands with none underlined
   when ``level_display`` was missing.

These tests render the real templates through ``trmnlp`` — the same path
``scripts/render_fixtures.py`` takes — and assert on the resulting DOM.

Two rules keep the module useful rather than a chore. There are no golden
files: a byte-exact snapshot of framework output breaks on every version bump
and gets regenerated unread, which is worse than no test at all. And every
expectation is derived from the fixture JSON, so a fixture may be edited or
added without touching an assertion here.

Rendering needs Docker (or a local ``trmnlp``), which ``make check`` and CI's
``python`` job deliberately do not have, so the whole module skips cleanly
when no renderer is present.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO / "tests" / "fixtures"

# The renderer invocation is not reimplemented here: importing the script
# means a change to how fixtures are rendered is a change to what is tested.
sys.path.insert(0, str(REPO / "scripts"))
import render_fixtures  # noqa: E402

VIEWS = render_fixtures.VIEWS
LEVELS = ("N5", "N4", "N3", "N2", "N1")
EMPTY_STATE_TEXT = "Vocabulary unavailable"

#: Liquid delimiters. None may survive into output; a surviving one means a
#: tag was mistyped, orphaned, or left behind by an edit — defect 1's class.
LIQUID_DELIMITERS = ("{{", "}}", "{%", "%}")


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


FIXTURE_NAMES = sorted(p.stem for p in FIXTURE_DIR.glob("*.json"))
FIXTURES = {name: _load(FIXTURE_DIR / f"{name}.json") for name in FIXTURE_NAMES}

#: Payloads that cannot live in ``tests/fixtures/``.
#:
#: ``test_payload_schema.test_no_fixture_contains_markup`` forbids ``<`` and
#: ``>`` anywhere in a fixture file — rightly, since the builder never emits
#: them — which is exactly what an escaping test needs. And every fixture on
#: disk is rendered by ``scripts/render_fixtures.py`` into ``dist/renders``,
#: which CI uploads as the artefact a human reviews by eye; a deliberately
#: malformed card does not belong in that gallery. Both payloads are rendered
#: alongside the fixtures here and go nowhere near the repository.
SYNTHETIC: dict[str, dict] = {
    "synthetic_markup_in_data": {
        "schema_version": "3.0",
        "level": "n3",
        "level_display": "N3",
        "dataset_version": "fixture",
        "selection_version": "1",
        "slot": {"index": 0, "seconds": 600, "count": 4096},
        "sequence": {"position": 42, "pool": 650},
        "_settings": {"show_example_translation": True},
        "word": {
            "id": "demo:<hostile>",
            "surface": "<b>注</b>意",
            "reading": "ちゅうい",
            "ruby_segments": [
                {"base": "<b>注</b>", "reading": "<i>ちゅう</i>"},
                {"base": "意", "reading": "い"},
            ],
            "display_gloss": "caution <script>alert(1)</script>",
            "example": {
                "ja": "<img src=x onerror=alert(1)>に注意。",
                "en": "Mind the <a href='#'>gap</a> & the step.",
            },
            "display": {"word_size": "short", "example_size": "normal"},
            "level": "N3",
        },
    },
    # Defect 4 in its original form: no level to underline. The strip must
    # disappear rather than list all five bands with none marked.
    "synthetic_unknown_level": {
        "schema_version": "3.0",
        "level": "n3",
        "dataset_version": "fixture",
        "selection_version": "1",
        "slot": {"index": 0, "seconds": 600, "count": 4096},
        "sequence": {"position": 42, "pool": 650},
        "word": {
            "id": "demo:本",
            "surface": "本",
            "reading": "ほん",
            "ruby_segments": [{"base": "本", "reading": "ほん"}],
            "display_gloss": "book",
            "display": {"word_size": "short", "example_size": "normal"},
            "level": "N3",
        },
    },
}

PAYLOADS: dict[str, dict] = {**FIXTURES, **SYNTHETIC}
ALL_NAMES = sorted(PAYLOADS)

#: Fixtures that carry a card, i.e. everything but the empty state.
CARD_NAMES = [n for n in FIXTURE_NAMES if FIXTURES[n].get("word", {}).get("surface")]


def card(name: str) -> dict:
    return PAYLOADS[name]["word"]


def setting(name: str, key: str) -> bool:
    return bool(PAYLOADS[name].get("_settings", {}).get(key, False))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _skip_reason() -> str | None:
    """Why rendering is impossible here, or None when it is possible.

    ``make check`` and CI's ``python`` job are documented as needing neither
    network nor Docker, so an absent renderer must skip, never fail — and the
    reason must say what to run.
    """
    if render_fixtures.have_local_trmnlp():
        return None
    image = render_fixtures.DOCKER_IMAGE
    if shutil.which("docker") is None:
        return (
            f"no renderer: Docker is not installed and `trmnlp` is not on PATH. "
            f"Install Docker and run `make trmnlp-image` to build {image}."
        )
    probe = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip().splitlines()
        return (
            f"no renderer: `docker image inspect {image}` failed"
            f"{' (' + detail[-1] + ')' if detail else ''}. "
            f"Run `make trmnlp-image`, or set KOTOBA_TRMNLP_IMAGE."
        )
    return None


SKIP_REASON = _skip_reason()
pytestmark = pytest.mark.skipif(SKIP_REASON is not None, reason=SKIP_REASON or "")


def _render_one(name: str, payload: dict) -> tuple[str, dict[str, str] | str]:
    """Render every view of *payload*; return its HTML, or an error string.

    Mirrors ``render_fixtures.render_fixture`` but keeps the output in memory:
    the tests must not depend on, or disturb, ``dist/renders``.
    """
    with tempfile.TemporaryDirectory(prefix=f"kotoba-test-{name}-") as tmp:
        project = Path(tmp)
        shutil.copytree(REPO / "src", project / "src")
        (project / ".trmnlp.yml").write_text(
            yaml.safe_dump(
                render_fixtures.build_config(payload),
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        result = render_fixtures.run_trmnlp(project, png=False)
        if result.returncode != 0:
            detail = result.stderr.strip()[-1500:]
            return name, f"trmnlp exited {result.returncode}: {detail}"
        views = {}
        for view in VIEWS:
            path = project / "_build" / f"{view}.html"
            if not path.is_file():
                return name, f"no output for view {view!r}"
            views[view] = path.read_text(encoding="utf-8")
    return name, views


class Renders:
    """Rendered HTML for every payload, with parsed documents memoised."""

    def __init__(self, html: dict[str, dict[str, str]]) -> None:
        self._html = html
        self._dom: dict[tuple[str, str], Element] = {}

    def html(self, name: str, view: str) -> str:
        return self._html[name][view]

    def dom(self, name: str, view: str) -> Element:
        key = (name, view)
        if key not in self._dom:
            self._dom[key] = parse(self._html[name][view])
        return self._dom[key]

    def card_root(self, name: str, view: str) -> Element:
        """The ``.kotoba`` container: everything the card owns, title bar aside."""
        (root,) = self.dom(name, view).find_all(cls="kotoba")
        return root


@pytest.fixture(scope="session")
def renders() -> Renders:
    """Render every payload once. Each render is a container start-up, so
    doing this per test would cost minutes rather than seconds."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = dict(pool.map(lambda kv: _render_one(*kv), PAYLOADS.items()))
    failures = {n: r for n, r in results.items() if isinstance(r, str)}
    if failures:
        pytest.fail(
            "trmnlp failed to render:\n"
            + "\n".join(f"  {n}: {msg}" for n, msg in sorted(failures.items()))
        )
    return Renders(results)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# A very small DOM
# ---------------------------------------------------------------------------
#
# stdlib only, deliberately: an HTML parser is a dependency this repository
# would otherwise not have, and the assertions below need nothing beyond
# "find elements by tag or class, and read their text".

VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)

#: Text inside these is code, not content, and must never be asserted on.
OPAQUE_TAGS = frozenset({"style", "script"})


class Element:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: dict[str, str | None]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[Element | str] = []

    @property
    def classes(self) -> list[str]:
        return (self.attrs.get("class") or "").split()

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.walk()

    def find_all(self, tag: str | None = None, cls: str | None = None) -> list[Element]:
        return [
            el
            for el in self.walk()
            if el is not self
            and (tag is None or el.tag == tag)
            and (cls is None or cls in el.classes)
        ]

    def find(self, tag: str | None = None, cls: str | None = None) -> Element | None:
        found = self.find_all(tag, cls)
        return found[0] if found else None

    @property
    def text(self) -> str:
        """Visible text of this subtree, with CSS and scripts left out."""
        if self.tag in OPAQUE_TAGS:
            return ""
        parts = []
        for child in self.children:
            parts.append(child if isinstance(child, str) else child.text)
        return "".join(parts)

    def __repr__(self) -> str:  # pragma: no cover - assertion output only
        cls = " ".join(self.classes)
        return f"<{self.tag}{' class=' + cls if cls else ''}>"


class _Parser(HTMLParser):
    def __init__(self) -> None:
        # Entities are decoded, so an escaped `<` from data arrives as text —
        # exactly the distinction the escaping tests turn on.
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", {})
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        element = Element(tag, dict(attrs))
        self._stack[-1].children.append(element)
        if tag not in VOID_TAGS:
            self._stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self._stack[-1].children.append(Element(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for depth in range(len(self._stack) - 1, 0, -1):
            if self._stack[depth].tag == tag:
                del self._stack[depth:]
                return

    def handle_data(self, data):
        self._stack[-1].children.append(data)


def parse(html: str) -> Element:
    parser = _Parser()
    parser.feed(html)
    parser.close()
    return parser.root


def sequence_of(element: Element) -> list[tuple[str, str] | str]:
    """Flatten a word container into ruby pairs and bare runs of text.

    Whitespace-only text between elements is layout, not content, and is
    dropped; adjacent bare runs are merged, so the result compares directly
    against the payload's ruby segments.
    """
    out: list[tuple[str, str] | str] = []
    for child in element.children:
        if isinstance(child, str):
            if not child.strip():
                continue
            if out and isinstance(out[-1], str):
                out[-1] += child
            else:
                out.append(child)
        elif child.tag == "ruby":
            rb, rt = child.find("rb"), child.find("rt")
            out.append((rb.text if rb else child.text, rt.text if rt else ""))
        else:  # pragma: no cover - would itself be the bug
            out.append(child.text)
    return out


def expected_sequence(word: dict) -> list[tuple[str, str] | str]:
    """The same flattening, derived from the payload rather than the output."""
    out: list[tuple[str, str] | str] = []
    for segment in word["ruby_segments"]:
        reading = segment.get("reading")
        if reading:
            out.append((segment["base"], reading))
        elif out and isinstance(out[-1], str):
            out[-1] += segment["base"]
        else:
            out.append(segment["base"])
    return out


def level_bands(element: Element) -> list[tuple[str, bool]] | None:
    """The title bar's level strip as (label, is_current), or None if absent."""
    strip = element.find(cls="kotoba-levels")
    if strip is None:
        return None
    return [
        (band.text.strip(), "is-current" in band.classes)
        for band in strip.find_all("span")
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ALL_NAMES)
def test_no_unrendered_liquid_reaches_the_panel(renders, name):
    """A surviving delimiter means a tag was orphaned by an edit.

    Defect 1 shipped a leftover `{% assign word = nil %}` from a failed string
    replace; the block itself rendered to nothing, but its class of mistake is
    exactly this. The check is over the whole document, CSS included, because
    that is where a stray tag would sit unnoticed.
    """
    for view in VIEWS:
        html = renders.html(name, view)
        found = [token for token in LIQUID_DELIMITERS if token in html]
        assert found == [], f"{name}/{view} contains unrendered Liquid {found}"


@pytest.mark.parametrize("name", CARD_NAMES)
def test_the_word_is_on_screen(renders, name):
    """Defect 1 in one assertion: the card renders, and is not the empty state.

    The surface is reconstructed from the base text only — reading the whole
    element would interleave the furigana — so this also proves the ruby bases
    concatenate back to the word the payload asked for.
    """
    word = card(name)
    for view in VIEWS:
        root = renders.card_root(name, view)
        element = root.find(cls="kotoba-word")
        assert element is not None, f"{name}/{view} has no word element"
        bases = "".join(
            part if isinstance(part, str) else part[0]
            for part in sequence_of(element)
        )
        assert bases == word["surface"], f"{name}/{view}"
        assert EMPTY_STATE_TEXT not in root.text, f"{name}/{view}"


@pytest.mark.parametrize("view", VIEWS)
def test_the_empty_state_says_so(renders, view):
    """A payload without a card must say nothing rather than show a blank card."""
    root = renders.card_root("empty_state", view)
    assert EMPTY_STATE_TEXT in root.text
    assert root.find(cls="kotoba-word") is None
    # The level is still worth stating: it tells the reader which deck is
    # unavailable, not merely that something is.
    assert FIXTURES["empty_state"]["level_display"] in root.text


@pytest.mark.parametrize("name", CARD_NAMES)
def test_the_gloss_is_on_screen(renders, name):
    for view in VIEWS:
        gloss = renders.card_root(name, view).find(cls="kotoba-gloss")
        assert gloss is not None, f"{name}/{view} has no gloss"
        assert gloss.text.strip() == card(name)["display_gloss"], f"{name}/{view}"


class TestFurigana:
    """The whole reason the plugin exists: readings over kanji, and only kanji.

    Furigana over okurigana is the mistake every naive implementation makes,
    and it is unreadable on e-ink. The segmentation arrives precomputed, so
    the template's only job is to wrap the segments that have a reading and
    leave the rest alone — which is precisely what these assert.
    """

    @pytest.mark.parametrize("name", CARD_NAMES)
    def test_each_reading_sits_over_its_own_base(self, renders, name):
        expected = expected_sequence(card(name))
        for view in VIEWS:
            element = renders.card_root(name, view).find(cls="kotoba-word")
            assert sequence_of(element) == expected, f"{name}/{view}"

    @pytest.mark.parametrize("name", CARD_NAMES)
    def test_okurigana_is_never_wrapped_in_ruby(self, renders, name):
        """A segment with no reading must contribute bare text, nothing else."""
        rubies = [
            (segment["base"], segment["reading"])
            for segment in card(name)["ruby_segments"]
            if segment.get("reading")
        ]
        for view in VIEWS:
            element = renders.card_root(name, view).find(cls="kotoba-word")
            rendered = [
                (ruby.find("rb").text, ruby.find("rt").text)
                for ruby in element.find_all("ruby")
            ]
            assert rendered == rubies, f"{name}/{view}"

    def test_a_kana_only_word_has_no_ruby_at_all(self, renders):
        for view in VIEWS:
            element = renders.card_root("kana_only", view).find(cls="kotoba-word")
            assert element.find_all("ruby") == []
            assert element.text.strip() == FIXTURES["kana_only"]["word"]["surface"]

    @pytest.mark.parametrize("name", CARD_NAMES)
    def test_every_ruby_has_both_a_base_and_a_reading(self, renders, name):
        """An empty <rb> or <rt> is a floating accent mark on the panel."""
        for view in VIEWS:
            element = renders.card_root(name, view).find(cls="kotoba-word")
            for ruby in element.find_all("ruby"):
                rb, rt = ruby.find("rb"), ruby.find("rt")
                assert rb is not None and rb.text.strip(), f"{name}/{view}"
                assert rt is not None and rt.text.strip(), f"{name}/{view}"


class TestLevelStrip:
    """Defect 4: the strip listed all five bands with none underlined.

    The strip is a promise about the deck — "these are the levels your cards
    come from, and this one is today's". Both halves have to be true at once.
    """

    @pytest.mark.parametrize("name", FIXTURE_NAMES)
    def test_the_strip_is_cumulative_and_marks_exactly_one_band(self, renders, name):
        payload = PAYLOADS[name]
        expected = LEVELS[: LEVELS.index(payload["level_display"]) + 1]
        current = payload.get("word", {}).get("level") or payload["level_display"]
        for view in VIEWS:
            bands = level_bands(renders.dom(name, view))
            assert bands is not None, f"{name}/{view} has no level strip"
            assert [label for label, _ in bands] == list(expected), f"{name}/{view}"
            marked = [label for label, is_current in bands if is_current]
            assert marked == [current], f"{name}/{view}"

    def test_the_easiest_deck_is_a_single_band(self, renders):
        assert level_bands(renders.dom("level_n5", "full")) == [("N5", True)]

    def test_the_hardest_deck_shows_every_band(self, renders):
        bands = level_bands(renders.dom("level_n1", "full"))
        assert [label for label, _ in bands] == list(LEVELS)
        assert [label for label, current in bands if current] == ["N1"]

    def test_a_card_from_an_easier_level_underlines_that_level(self, renders):
        """The interesting case: an N3 deck showing an N4 card marks N4."""
        assert level_bands(renders.dom("level_strip_middle", "full")) == [
            ("N5", False),
            ("N4", True),
            ("N3", False),
        ]

    def test_an_unknown_level_shows_no_strip_rather_than_a_wrong_one(self, renders):
        """Defect 4 exactly. Five bands and no underline is a confident lie;
        the honest fallback is the plain label."""
        for view in VIEWS:
            document = renders.dom("synthetic_unknown_level", view)
            assert level_bands(document) is None, view
            instance = document.find(cls="instance")
            assert instance.text.strip() == "Kotoba", view

    def test_progress_appears_only_when_the_setting_asks_for_it(self, renders):
        """`show_rotation_progress` is off by default and must stay off."""
        sequence = FIXTURES["with_progress"]["sequence"]
        wanted = f"{sequence['position']}/{sequence['pool']}"
        assert wanted in renders.dom("with_progress", "full").find(cls="instance").text
        for name in CARD_NAMES:
            if setting(name, "show_rotation_progress"):
                continue
            text = renders.dom(name, "full").find(cls="instance").text
            assert "/" not in text, f"{name} leaked rotation progress"


class TestLayoutSuppression:
    """Each view's comment states what it drops; the drops are load-bearing.

    Half-horizontal has one clamped example line and no room for a
    translation under it. Quadrant has no room for a sentence at all. Both
    would look merely cramped rather than broken, so nothing but a test
    catches a regression here.
    """

    @pytest.mark.parametrize("view", ("half_horizontal", "half_vertical", "quadrant"))
    @pytest.mark.parametrize("name", CARD_NAMES)
    def test_the_small_views_never_show_the_translation(self, renders, name, view):
        root = renders.card_root(name, view)
        assert root.find(cls="kotoba-example-en") is None, f"{name}/{view}"

    @pytest.mark.parametrize("name", CARD_NAMES)
    def test_the_quadrant_shows_no_example_at_all(self, renders, name):
        root = renders.card_root(name, "quadrant")
        assert root.find(cls="kotoba-example") is None
        assert root.find(cls="kotoba-example-block") is None

    @pytest.mark.parametrize("name", CARD_NAMES)
    def test_the_full_view_shows_the_example_when_there_is_one(self, renders, name):
        example = card(name).get("example", {}).get("ja")
        rendered = renders.card_root(name, "full").find(cls="kotoba-example")
        if example is None:
            assert rendered is None
        else:
            assert rendered is not None and rendered.text.strip() == example

    @pytest.mark.parametrize("name", CARD_NAMES)
    def test_the_translation_follows_its_setting(self, renders, name):
        """Off by default: an unset custom field must not turn it on."""
        word = card(name)
        wanted = setting(name, "show_example_translation") and bool(
            word.get("example", {}).get("en")
        )
        rendered = renders.card_root(name, "full").find(cls="kotoba-example-en")
        if not wanted:
            assert rendered is None, f"{name} showed an unrequested translation"
        else:
            assert rendered.text.strip() == word["example"]["en"]

    @pytest.mark.parametrize("name", CARD_NAMES)
    def test_half_vertical_drops_an_example_that_would_crowd_the_word(
        self, renders, name
    ):
        display = card(name).get("display", {})
        crowded = (
            display.get("example_size") == "tiny" or display.get("word_size") == "xlong"
        )
        rendered = renders.card_root(name, "half_vertical").find(cls="kotoba-example")
        assert (rendered is None) == (
            crowded or not card(name).get("example", {}).get("ja")
        ), name

    @pytest.mark.parametrize("name", CARD_NAMES)
    def test_the_word_carries_its_size_class(self, renders, name):
        """The size classes are the only thing keeping a long word on one line."""
        expected = {"medium": "is-medium", "long": "is-long", "xlong": "is-xlong"}.get(
            card(name)["display"]["word_size"]
        )
        for view in VIEWS:
            classes = renders.card_root(name, view).find(cls="kotoba-word").classes
            sizes = [c for c in classes if c.startswith("is-")]
            assert sizes == ([expected] if expected else []), f"{name}/{view}"


class TestEscaping:
    """Every data-derived value passes through Liquid's `escape`.

    The corpus validator already refuses `<` and `>` in data, so this can only
    be exercised by a payload built here — see SYNTHETIC. That belt-and-braces
    ordering is the point: the validator is the guard, the filter is the
    backstop, and this is what proves the backstop is still wired up.
    """

    NAME = "synthetic_markup_in_data"

    @pytest.mark.parametrize("view", VIEWS)
    def test_markup_in_data_arrives_as_text(self, renders, view):
        root = renders.card_root(self.NAME, view)
        word = card(self.NAME)
        assert word["display_gloss"] in root.find(cls="kotoba-gloss").text

    @pytest.mark.parametrize("view", VIEWS)
    def test_markup_in_data_creates_no_elements(self, renders, view):
        """The tags in the payload must not become nodes in the card."""
        root = renders.card_root(self.NAME, view)
        tags = {element.tag for element in root.walk()}
        assert tags <= {"div", "ruby", "rb", "rt"}, sorted(tags)

    @pytest.mark.parametrize("view", VIEWS)
    def test_no_raw_angle_bracket_from_data_reaches_the_output(self, renders, view):
        """Fixture-driven: every string in the payload that contains a bracket
        must appear escaped, and never verbatim, in the rendered HTML."""
        html = renders.html(self.NAME, view)
        for value in self._strings(PAYLOADS[self.NAME]):
            if "<" not in value and ">" not in value:
                continue
            assert value not in html, f"{value!r} reached {view} unescaped"
        assert "&lt;script&gt;" in html, "the gloss should be escaped, not dropped"

    @staticmethod
    def _strings(node) -> list[str]:
        if isinstance(node, str):
            return [node]
        if isinstance(node, dict):
            return [s for k, v in node.items() if not k.startswith("_")
                    for s in TestEscaping._strings(v)]
        if isinstance(node, list):
            return [s for v in node for s in TestEscaping._strings(v)]
        return []
