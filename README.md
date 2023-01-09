# Installation
`git clone https://github.com/Kyle-Kyle/top4grep`

# Setup
`python build_db.py`

# Query
`python top4grep.py -k <keywords>`. For example, `python top4grep.py -k linux,kernel`
Currently, the query is just a case-insensitive match (just like grep). The returned results must contains all the input keywords (papers containing keyword1 AND keyword2 AND ...). Support for `OR` operation (papers containing keyword1 OR keyword2) is missing, but will be added in the future.

# Screenshot
![screenshot](https://raw.githubusercontent.com/Kyle-Kyle/top4grep/master/img/screenshot.png)

# TODO
- [ ] grep in abstract
- [ ] fuzzy match
- [ ] complex search logic (`OR` operation)
