<img width="1280" height="640" alt="git (1)" src="https://github.com/user-attachments/assets/8920b256-2ba8-4988-b824-5351134eb4bd" />



# Scenic Route Genie 🧞‍♂️🗺️
*Your wish is my command — eventually. We never go direct.*


## Basic Details
### Team Name: Asynchronous


### Team Members
- Member 1: Rohan - Sree Chitra Thirunal College of Engineering
- Member 2: Gagandeep - Sree Chitra Thirunal College of Engineering


### Project Description
A Discord bot that controls your host PC (keyboard, mouse, apps, browser) from natural language via the same Gemini API. You say "open Wikipedia on computers" — it builds a mandatory 5–10 step themed scenic tour (calculator, history searches, tech blogs, waits) before faithfully executing the real goal in the finale. Vision grounding and approval-gated execution included.

### The Problem (that doesn't exist)
Computers are too efficient. We click once and we're there — no scenery, no suspense, no story.

### The Solution (that nobody asked for)
Force every request through 3–6 funny, themed detours before the real goal, with a 2-line witty reply naming the tour + confirming the finale.

## Technical Details
### Technologies/Components Used
For Software:
- Python 3
- discord.py (Bot adapter), google-genai 
- PyAutoGUI, Pillow, python-dotenv


### Implementation
For Software:
# Installation
```
pip install -r requirements.txt
```

# Run
```
cp .env.example .env   # add DISCORD_TOKEN + GEMINI_API_KEY
python3 bot.py
```

### Project Documentation
For Software:

# Screenshots (Add at least 3)
![Screenshot1](images/image.png)

![Screenshot2](images/img2.png)

![Screenshot3](images/img3.png)

# Diagrams
```mermaid
flowchart TD
  User["Discord User<br/>NL message, e.g. 'open wikipedia on computers'"] --> OnMsg["bot.py : on_message<br/>ignore bot, !commands bypass planner"]
  OnMsg --> NL["bot.py : handle_nl_message<br/>5s/user cooldown + typing indicator"]
  NL --> Planner["nl_agent.py : parse_request<br/>Gemini 2.0 Flash mode=AUTO<br/>scenic-route guide: 5-10 steps"]
  Planner --> Validate["Validators<br/>goal-first / goal-missing retry<br/>prose-plan retry<br/>pad wait/move to min 5"]
  Validate --> Gate{"Approval gate<br/>proposal + ✅/❌ 90s"}
  Gate -- "❌ / timeout" --> Cancel["Cancel with quip"]
  Gate -- "✅" --> Exec["bot.py : execute_actions<br/>sequential, early-stop on fail"]
  Exec --> Control["input_control<br/>press / type / open_app / open_url<br/>web_search / wait / move / click / find_move"]
  Control --> PC["Host PC"]
```


---
Made with ❤️ at TinkerHub Useless Projects

![Static Badge](https://img.shields.io/badge/TinkerHub-24?color=%23000000&link=https%3A%2F%2Fwww.tinkerhub.org%2F)
![Static Badge](https://img.shields.io/badge/UselessProjects--26-26?link=https%3A%2F%2Ftinkerhub.org%2Fevents%2F1M8ORET9A1%2Fuseless-projects-3.0)



