# top4grep
A grep tool for the top 4 security conferences

## Installation
```
git clone https://github.com/Kyle-Kyle/top4grep
cd top4grep
pip3 install -e ./top4grep
```

## Usage 
### Database Initialization
If you want to update the papers stored in `papers.db`, you can recreate it with:
```bash
top4grep --build-db
```

Which will build the db wherever you run it.

### Query
```bash
top4grep -k <kerywords>
```

For example, `python top4grep.py -k linux,kernel`
Currently, the query is just a case-insensitive match (just like grep). The returned results must contains all the input keywords (papers containing keyword1 AND keyword2 AND ...). Support for `OR` operation (papers containing keyword1 OR keyword2) is missing, but will be added in the future.

## Screenshot
![screenshot](https://raw.githubusercontent.com/Kyle-Kyle/top4grep/master/img/screenshot.png)

## TODO
- [ ] grep in abstract
- [ ] fuzzy match
- [ ] complex search logic (`OR` operation)
