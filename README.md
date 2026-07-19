# VNForge

**A desktop app that compiles plain prose scenes into structured visual novel scripts using AI.**

Paste a scene, pick a genre and branching depth, hit compile — VNForge returns a ready-to-use Ren'Py script, branching choices, asset cues for your art team, and production notes. No prompt engineering required.

Built for the IBM watsonx Challenge — July 2025.

---

## What it does

- Converts plain prose into valid **Ren'Py script syntax** in one click
- Generates **branching player choices** at configurable depth (shallow / medium / deep)
- Produces an **asset cue list** (backgrounds, character sprites, music, sound) for the art and audio team
- Outputs **production notes** with pacing, animation, and voice acting reminders
- Supports **scene chaining** — compile a follow-up scene with full context from the previous one and the player's chosen route
- Exports to `.rpy`, `.txt` asset list, and `.md` report

---

## AI providers

VNForge works with any of these — you choose on first launch:

| Provider | Cost | Notes |
|---|---|---|
| **IBM watsonx.ai** | Free (Lite plan) | Granite 3.1 8B Instruct. Requires API Key + Project ID. |
| **Google Gemini** | Free tier | Gemini 2.0 Flash. No card needed, 1 500 req/day. |
| **OpenRouter** | Free + paid | Access to many models. Free models available. |

---

## Requirements

- Python 3.10 or newer
- Internet connection (for AI API calls)
- An API key from one of the providers above

All Python dependencies are installed automatically on first run.

---

## Installation & setup

**1. Clone the repo**
```bash
git clone https://github.com/your-org/vnforge.git
cd vnforge
```

**2. Run the app**
```bash
python run.py
```

That's it. On first launch:
- Any missing Python packages are installed automatically
- A setup window opens asking you to choose an AI provider
- Enter your API key — it is validated live before anything is saved
- Your credentials are written to a local `.env` file that never leaves your machine

Every launch after that goes straight to the main app.

---

## How to use

### Compiling a scene

1. Paste a prose scene into the **Scene Input** box on the left
2. Choose a **Genre** from the dropdown (Romance, Mystery, Thriller, Fantasy, Sci-Fi, Slice of Life)
3. Choose a **Branching Depth**:
   - **Shallow** — 2 simple choices, minor consequences
   - **Medium** — 3 choices that affect story variables
   - **Deep** — 4+ choices with major route splits
4. Click **⚙ Compile Scene**
5. Results appear across four tabs on the right:
   - **Ren'Py Script** — copy-paste ready script block
   - **Choices** — branching options with route labels and consequences
   - **Asset Cues** — list of backgrounds, sprites, music, and sounds needed
   - **Production Notes** — developer reminders for animation, pacing, voice acting

### Continuing a scene

After compiling, a **Continue Scene** section appears below the compile button:

1. Pick the route you want to follow from the **route dropdown**
2. Paste your next prose scene into the input box
3. Click **↪ Continue Scene**

The model receives the previous scene's title, summary, and the chosen route's consequence — so the output stays narratively consistent.

### Exporting

Three export buttons appear below the output tabs:

- **Export .rpy** — saves the Ren'Py script as a `.rpy` file
- **Export Asset List** — saves the asset cues as a plain `.txt` file
- **Export Report (md)** — saves the full compiled scene as a `.md` report

All exports are saved to an `exports/` folder inside the project directory.

### Changing provider

Click **Change Provider** in the top-right corner of the main window at any time to switch to a different AI provider or update your API key.

---

## Project structure

```
vnforge/
├── run.py                  # Entry point — run this
├── app.py                  # Desktop UI (CustomTkinter)
├── core/
│   ├── compiler.py         # compile_scene() and continue_scene()
│   ├── model_client.py     # API calls to watsonx / Gemini / OpenRouter
│   ├── prompts.py          # Prompt construction
│   ├── exporters.py        # File export functions
│   └── schemas.py          # Pydantic data models
├── samples/                # Example prose scenes to test with
├── requirements.txt
└── .env.example            # Credential template (never commit .env)
```

---

## Security

- API keys are stored only in `.env` on your local machine
- `.env` is listed in `.gitignore` and will never be committed to this repo
- `.env.example` contains no real keys — only empty placeholders

---

## Built with

- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) — desktop UI
- [Pydantic](https://docs.pydantic.dev/) — data validation
- [python-dotenv](https://github.com/theskumar/python-dotenv) — environment config
- IBM watsonx.ai / Google Gemini / OpenRouter — AI inference
