# NOTICE

This file is generated from `data/sources.yml` by `kotoba validate --write-notice`.
Do not edit it by hand.

The **code** in this repository is licensed under the MIT Licence (see
`LICENSE`). The **vocabulary data** is not: it is derived from the third-party
sources listed below and remains subject to their licences. A permissive code
licence does not relicense the data.

JLPT level assignments in this repository are community-estimated. The Japan
Foundation and JEES no longer publish an official vocabulary specification, so
no list here is, or claims to be, an official JLPT vocabulary list.


## Jonathan Waller's JLPT Resources, via stephenmk/yomitan-jlpt-vocab

- **Source ID:** `jlpt-waller`
- **Homepage:** https://github.com/stephenmk/yomitan-jlpt-vocab
- **Retrieved:** 2026-08-09
- **Version:** HEAD (original_data/n1..n5.csv)
- **Licence:** CC-BY-SA-4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
- **Fields used:** jmdict_seq, kana, kanji, waller_definition
- **Checksum:** `sha256:07dc6f197b51cc076c65c3c (n5.csv; see scripts/fetch_sources.py --checksums for the full set)`

> JLPT level estimates compiled by Jonathan Waller (http://www.tanos.co.uk/jlpt/, Creative Commons Attribution licence), redistributed with JMdict entry identifiers by stephenmk/yomitan-jlpt-vocab under CC BY-SA 4.0.

**Redistribution notes:** Level assignments are community estimates, not an official JLPT specification. The Japan Foundation and JEES stopped publishing vocabulary lists in 2010. These lists are over a decade old and are the same data shown by jisho.org. They must never be described as official or endorsed.


## JMdict, via scriptin/jmdict-simplified

- **Source ID:** `jmdict`
- **Homepage:** https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project
- **Retrieved:** 2026-08-09
- **Version:** 3.6.2+20260803141815 (jmdict-examples-eng)
- **Licence:** CC-BY-SA-4.0 (https://www.edrdg.org/edrdg/licence.html)
- **Fields used:** id, sense.gloss, sense.partOfSpeech, sense.examples
- **Checksum:** `sha256:924f8297cec4d48eb4a313c (jmdict-examples-eng.json; see scripts/fetch_sources.py --checksums for the full digest)`

> JMdict is the property of the Electronic Dictionary Research and Development Group, and is used in conformance with the Group's licence. The project was started in 1991 by Jim Breen. JSON conversion by scriptin/jmdict-simplified, distributed under the same licence.

**Redistribution notes:** EDRDG requires that the usage and source of the files be acknowledged in documentation, publicity material and the project website, and that links to the licence be provided. Adding material to the files does not diminish the Group's copyright; no copyright is claimed here over the JMdict-derived content. Attribution is carried in README.md, NOTICE.md, the generated Pages index and the plugin description.


## JmdictFurigana by Doublevil

- **Source ID:** `jmdict-furigana`
- **Homepage:** https://github.com/Doublevil/JmdictFurigana
- **Retrieved:** 2026-08-09
- **Version:** 2.3.1+2026-07-25
- **Licence:** CC-BY-SA-4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
- **Fields used:** surface, reading, ruby segment offsets
- **Checksum:** `sha256:2d5a6a11195ecfbaa565867 (JmdictFurigana.txt; see scripts/fetch_sources.py --checksums for the full digest)`

> Furigana segmentation from JmdictFurigana by Doublevil, distributed under the same licence as JMdict (Creative Commons Attribution-ShareAlike).

**Redistribution notes:** The repository's LICENSE file states MIT, which covers the C# generator. The README states the data is distributed under the same licence as JMdict. As a JMdict derivative the data is treated here as CC BY-SA 4.0, which is the stricter and safer reading.


## Tatoeba Project example sentences

- **Source ID:** `tatoeba`
- **Homepage:** https://tatoeba.org/
- **Retrieved:** 2026-08-09
- **Version:** via jmdict-examples-eng 3.6.2+20260803141815
- **Licence:** CC-BY-2.0-FR (https://creativecommons.org/licenses/by/2.0/fr/)
- **Fields used:** sentence text (Japanese), sentence text (English), sentence id

> Example sentences from the Tatoeba Project (https://tatoeba.org/), licensed CC BY 2.0 FR, selected and sense-aligned by the EDRDG examples build. Individual sentence authors are credited on Tatoeba; each entry records its Tatoeba sentence ID, which resolves to https://tatoeba.org/en/sentences/show/<id>.

**Redistribution notes:** Tatoeba's terms ask for attribution of the individual sentence author. The upstream export carries only the numeric sentence ID, not the author name, so attribution here is at sentence-ID level plus a project-level credit. This is the customary practice for JMdict-derived example data and is a pragmatic rather than literal reading of the per-author clause.
