# Khoj: exact-answer web retrieval agent

Entry for AMD AI League, Match 4 (Intelligent Web Information Retrieval), by Akshay Wagh.

Khoj (Hindi for "search") takes a natural-language question and an optional start URL, walks the site, and returns one exact value with the page it came from. Not a summary, not a list of links.

## How it works
1. Writes a well-formed placeholder JSON first, so a timeout never leaves an empty slot.
2. Classifies the question into an answer type: price, date, version, phone, email, number, name or text.
3. Fetches the start URL (or a keyless DuckDuckGo search when none is given), cleans HTML to text with table rows kept, and follows same-site links whose text matches the question.
4. Extracts typed candidates with rules and ranks them by term overlap and distance to query words.
5. If local weights are baked in (Qwen3-4B-Instruct on the AMD GPU via ROCm PyTorch), the model picks among the top passages and its answer must appear verbatim in a passage. Otherwise the rule path answers.
6. Abstains with an empty answer when nothing on the pages supports one.

No API keys. Hard 24 second deadline per query.

Test run: 6/6 offline questions answered correctly (rule path, model off).

## Run
```
python3 app.py --id q1 --query "What is the price of the Pro plan?" --url https://example.com
# or drop {"id":..,"query":..,"url":..} files in /app/input
```
Output: `/app/output/<id>_output.json` with `answer`, `citations`, `sources`, `source_url`, `confidence`.

## Docker (AMD ROCm)
```
docker build -t khoj-match4 .
docker run --rm --device=/dev/kfd --device=/dev/dri -v $PWD/out:/app/output khoj-match4 --id q1 --query "..." --url "..."
```

## Tests
`python3 test_agent.py` runs 6 offline questions over a built-in 4-page fixture site (price in a table, version, phone, email, date, founder name), following links from the home page.

## License
MIT
