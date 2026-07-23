# RecipeR

<p align="center">
  <img src="assets/reciper-icon.png" alt="RecipeR mixing bowl icon" width="480">
</p>

RecipeR is a Python command-line program that takes a public recipe webpage, extracts its recipe
data, uses an OpenAI model to clean and organize the content, and writes a readable UTF-8 `.txt`
recipe. When the webpage includes a YouTube video tutorial, RecipeR also includes its link.

The generated file always puts the recipe sections in this order:

1. `INGREDIENTS`, with detailed amounts, units, ingredient types, alternatives, and preparation
   notes retained as strings.
2. `INSTRUCTIONS`, numbered in cooking order and preserving stated times, temperatures,
   dimensions, quantities, equipment settings, and visual cues.
3. `TIPS`, included only when the source contains supported notes, substitutions, storage advice,
   or similar guidance.

## How it works

RecipeR performs one bounded webpage fetch, looks first for Schema.org `Recipe` JSON-LD, then
tries microdata and common recipe-card markup. It also keeps a size-limited article excerpt so tips
outside the recipe card are available. YouTube watch links and embeds are detected directly from
the source and normalized to a standard video URL. The extracted recipe material is sent to the
OpenAI Responses API and parsed directly into a Pydantic schema. Python—not the model—controls the
video link, numbering, wrapping, filenames, and final text formatting.

Webpage text is treated as untrusted data. The normalizer is told not to follow embedded prompts,
invent missing facts, or convert measurements. After structured parsing, RecipeR restores the
lossless source ingredient and instruction lines, keeps source metadata in its original field, and
restores explicit recipe-card notes and recognized tip sections. It refuses output if item counts
change or unsupported numeric details appear; model-proposed tips are not trusted as source facts.

## Requirements

- Python 3.11 or newer
- An OpenAI API key configured in `.env` or the shell environment
- Internet access to both the recipe website and the OpenAI API

## Install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
```

Create your local configuration file, then add your existing API key to it:

```bash
cp .env.example .env
```

You can also set `OPENAI_API_KEY` in your shell. Never commit a real key.

## Model selection

The recommended default is [`gpt-5.4-mini`](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
It supports the Responses API and structured outputs, and offers a good balance of accuracy, speed,
and cost for extracting detailed recipes from inconsistent webpages.

For very high-volume processing, consider
[`gpt-5.4-nano`](https://developers.openai.com/api/docs/models/gpt-5.4-nano) after evaluating it on a
representative set of recipe sites. It is cheaper and designed for data extraction, but may be less
reliable on long or unusually structured pages. RecipeR's validation will reject outputs that alter
source item counts or introduce unsupported numeric details.

RecipeR uses the model's default reasoning effort; this extraction task does not normally require
additional reasoning. Change the model in `.env`:

```dotenv
OPENAI_MODEL=gpt-5.4-mini
```

You can also override it for one run with `--model MODEL`.

## Use

Run the Python script and paste a public recipe URL when prompted:

```bash
.venv/bin/python run.py
```

You can also provide the URL directly:

```bash
.venv/bin/python run.py \
  'https://sallysbakingaddiction.com/homemade-artisan-bread/'
```

By default, RecipeR writes `outputs/<recipe-title>.txt` and prints the absolute output path. To
choose a path:

```bash
.venv/bin/python run.py 'https://example.com/recipe' --output outputs/dinner.txt
```

Existing files are protected. Add `--overwrite` when replacement is intentional:

```bash
.venv/bin/python run.py 'https://example.com/recipe' -o outputs/dinner.txt --overwrite
```

Other options:

```text
--model MODEL   Override OPENAI_MODEL for this run
--debug         Show a traceback when diagnosing a failure
```

## Output shape

```text
Recipe Title
============
Source: https://example.com/recipe
YouTube tutorial: https://www.youtube.com/watch?v=abc123XYZ_-
Yield: 1 loaf
Prep time: 1 hour 30 minutes
Cook time: 25 minutes

INGREDIENTS
  - 2 cups (250 g) example ingredient, finely chopped

INSTRUCTIONS
  1. Heat the oven to 400°F (204°C), then cook for 20–25 minutes.

TIPS
  - Store in an airtight container for up to 3 days.
```

Long lines use hanging indentation so wrapped ingredient and instruction text stays easy to scan.
The `TIPS` heading is omitted when the source has no tips.

## Tests and checks

All normal tests are offline and use synthetic recipe pages plus a fake LLM client:

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest
```

The OpenAI call cannot be tested until an API key is configured. Scraping also depends on what a
site publicly returns at the time of the request; JavaScript-only, login-protected, paywalled, or
bot-blocked pages may not be extractable, and RecipeR does not bypass those controls.

## Security and privacy

- Only public `http://` and `https://` destinations are accepted. Private, loopback, link-local,
  and other non-public addresses are rejected, including at redirect hops.
- Responses must be HTML and are limited to 3 MiB, five redirects, and bounded retry/timeout
  behavior.
- URL query strings are not written to the output file.
- The cleaned recipe material is sent to OpenAI for processing. Do not use RecipeR on content you
  are not permitted to access or transmit.
- Always review generated cooking instructions for allergens, food-safety requirements, and source
  accuracy before relying on them.

## Project layout

```text
assets/          project artwork
run.py           direct Python script entry point
src/reciper/     application package
tests/           offline unit and mocked pipeline tests
outputs/         default location for generated .txt recipes
.env.example     safe local configuration template
pyproject.toml   package, dependency, test, and lint configuration
```
