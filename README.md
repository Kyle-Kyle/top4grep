# top4grep
A grep tool for the top 4 security conferences, with cached raw fetches for repeatable literature review.

## Installation
```
git clone https://github.com/Kyle-Kyle/top4grep
cd top4grep
pip3 install -e .
```

## Usage 
### Database Initialization
If you want to update the papers stored in `papers.db`, you can recreate it with:
```bash
top4grep --build-db
```

The database and all cached raw fetches live under `top4grep/data/` inside the package directory, not in the current working directory.

Useful build filters:
```bash
top4grep --build-db --conference "IEEE S&P" --conference CCS --year-from 2021 --year-to 2026
top4grep --build-db --abstract --year-from 2023 --year-to 2024
```

### Cache Bundle Bootstrap
You can package the local database plus all cached raw fetches into one zip file:

```bash
top4grep --export-cache-bundle /tmp/top4grep-cache-bundle.zip
```

Current published bundle cutoff:

- snapshot date: `2026-03-12`
- download: `https://drive.google.com/file/d/1vAeDHNnDDKyXWPQTGLnlWnQchoRt9-_s/view?usp=sharing`
- expected usage: install the bundle first, then run incremental refreshes for anything added or corrected after `2026-03-12`

The bundle contains:

- `papers.db`
- `raw/dblp/...`
- `raw/publisher_html/...`
- `raw/openalex/...`
- `raw/semantic_scholar/...`
- `raw/pdf/...`

To install a downloaded bundle into the correct local package data directory:

```bash
top4grep --install-cache-bundle ~/Downloads/top4grep-cache-bundle.zip
```

If you want the downloaded snapshot to fully replace your current local data first:

```bash
top4grep --install-cache-bundle ~/Downloads/top4grep-cache-bundle.zip --replace-data
```

After installing a bundle, users can do only incremental refreshes for newer years instead of cold-crawling the full history again. For example:

```bash
top4grep --build-db --abstract --year-from 2024
```

Notes:

- `--abstract` updates existing rows in place when abstracts are missing and keeps papers even when their abstracts remain unavailable after all configured fallbacks
- rebuilds also remove stale rows that no longer appear in the latest source data
- the first abstract build for a new slice can take noticeably longer because publisher and OpenAlex data are fetched live
- rerunning the same abstract build is much faster because raw responses are cached under `top4grep/data/raw/`
- stored titles and authors are normalized automatically, so escaped HTML entities such as `&quot;` do not create duplicate rows
- abstract recovery currently tries publisher HTML, OpenAlex, Semantic Scholar, and PDF extraction from open conference paper links

### Query
```bash
top4grep -k <keywords>
```

For example:

```bash
top4grep -k linux,kernel
top4grep -k "linux,kernel|driver" --field all --year-from 2021
top4grep -k "supply,chain|dependency" --abstract --conference CCS
```

Query semantics:

- `,` means `AND`
- `|` means `OR`
- matching is case-insensitive and stemmed, so `exploiting` matches `exploit`
- `--field` supports `title`, `abstract`, `authors`, `conference`, and `all`
- `--abstract` is kept for compatibility and defaults query field selection to `abstract`

Raw source material is cached under:

- `top4grep/data/raw/dblp/html/`
- `top4grep/data/raw/dblp/api/`
- `top4grep/data/raw/publisher_html/`
- `top4grep/data/raw/openalex/`
- `top4grep/data/raw/semantic_scholar/`
- `top4grep/data/raw/pdf/`

The bundled cache installs into the same `top4grep/data/` location, so the normal build pipeline automatically reuses it.

## Screenshot
![screenshot](https://raw.githubusercontent.com/Kyle-Kyle/top4grep/master/img/screenshot.png)

## Status
- [x] grep in abstract
- [x] fuzzy match
- [x] complex search logic (`OR` operation)
