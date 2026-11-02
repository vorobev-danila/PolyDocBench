# Bundled Font Fallback

`NotoSansSymbols2/NotoSansSymbols2-Regular.ttf` is an unmodified upstream font
from [Google Fonts](https://github.com/google/fonts/tree/main/ofl/notosanssymbols2).
Copyright 2022 The Noto Project Authors. It is distributed under the included
SIL Open Font License 1.1 in `NotoSansSymbols2/OFL.txt`.

The primary document font remains DejaVu Sans. PolyDocBench uses the symbol font
only for missing characters that it actually supports, such as Unicode Control
Pictures in ASCII tables. Measurement and drawing share the same font runs.
Uncovered characters fail explicitly; this is not a universal script/shaping or
emoji fallback. The Docker image includes this directory.

Downloaded file SHA-256:
`7d5fb73b7ca67a6798101741f5d280a3d016a56a197afcd4199dbb57b4b82a21`.
