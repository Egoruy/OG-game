from flask import Flask, request, jsonify, send_from_directory, make_response
from flask_cors import CORS
import opengradient as og
import asyncio
import nest_asyncio
import json
import os
import time
import logging

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Async fix ─────────────────────────────────────────────────────────────────
nest_asyncio.apply()

# ── App setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder='.')
CORS(app)

# ── CSP middleware — fixes blob: blocked by Railway ───────────────────────────
@app.after_request
def add_headers(response):
    response.headers['Content-Security-Policy'] = (
        "default-src 'self' 'unsafe-inline' 'unsafe-eval' "
        "https://cdn.jsdelivr.net https://fonts.googleapis.com https://fonts.gstatic.com "
        "blob: data: *; "
        "img-src 'self' data: blob: https: *; "
        "worker-src 'self' blob:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net blob:; "
        "connect-src 'self' blob:;"
    )
    return response

# ── OG client ─────────────────────────────────────────────────────────────────
log.info("Initializing OpenGradient LLM client...")
llm = og.LLM(private_key=os.environ.get('PRIVATE_KEY'))

try:
    approval = llm.ensure_opg_approval(min_allowance=4.0)
    log.info(f"OPG allowance: {approval.allowance_after}")
except Exception as e:
    log.warning(f"Could not ensure OPG approval: {e}")

# ── OG context for quiz ───────────────────────────────────────────────────────
OG_CONTEXT = """
OpenGradient is a decentralized AI infrastructure platform. Key concepts:
1. TEE (Trusted Execution Environment): Hardware-isolated enclave where AI models run. Tamper-proof. No external access during execution. Used for verifiable inference.
2. Walrus: Decentralized storage network where AI models live. Censorship-proof, no single point of failure.
3. OpenGradient Model Hub: Repository of community-built AI models. Discoverable and callable on-chain.
4. MemSync: Multi-agent coordination protocol. Multiple AI bots share state on-chain.
5. Twin Function: Wraps a model call in a TEE enclave, producing a cryptographic attestation (Golden Seal). The blockchain verifies the seal.
6. x402 micropayment protocol: Pay-per-inference model. No API keys, no subscriptions.
7. ZKML: Zero-Knowledge Machine Learning — proving model output is correct without revealing weights.
8. VANILLA inference: Standard non-verified inference mode (cheaper, no proof).
9. On-chain verifiability: Every inference result can be verified on-chain via attestation or ZK proof.
10. Privacy by default: Models in TEE don't store user data between sessions.
"""

QUIZ_SYSTEM_PROMPT = f"""You are generating a quiz about OpenGradient decentralized AI platform for players who just completed an interactive game teaching these concepts.

The game had 4 levels:
- Level 1: Player talked to an AI that had no memory. They had to say "I am [name], remember me" to unlock a door. Concept: Privacy by default — TEE models don't store your data between sessions.
- Level 2: Player commanded two bots (Bot A and Bot B) by typing "press button". Bot A wrote its status to MemSync network, Bot B read it automatically and reacted. Concept: Multi-agent coordination via shared on-chain memory.
- Level 3: Player found a "Wall of Distortion" blocking the path. They opened the Model Hub terminal and chose the correct model (Pattern_Recognizer_v4) to decode the wall. Wrong choices were Data_Defragmenter and Crypto_Oracle. Concept: OpenGradient Model Hub — decentralized model repository on Walrus storage.
- Level 4: Player found a Crypto-Gate that only opened after initializing a Twin Function. The sequence: connect cable → seal TEE enclave → golden seal proof → gate opens. Concept: Twin Function wraps AI in TEE, produces cryptographic attestation.

Context:
{OG_CONTEXT}

Generate exactly 10 multiple-choice quiz questions. EASY difficulty — players just played the game, questions should reference what they experienced.

RULES:
- Questions should feel familiar ("In Level 1...", "When you commanded Bot A...", "Which model did you use to...", "What happened when you initialized the Twin...")
- Simple, direct questions — no tricks
- Wrong answers should be obviously wrong to someone who played
- Distribute correct answers: mix of A, B, C, D positions — NO more than 2 same index in a row

Return ONLY a JSON array, no markdown, no backticks:
[
  {{
    "q": "question text",
    "options": ["option A", "option B", "option C", "option D"],
    "answer": 0,
    "explain": "short explanation referencing the game"
  }}
]

"answer" = 0-based index (0=A, 1=B, 2=C, 3=D). Spread answers across A/B/C/D evenly."""


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/models/<path:filename>')
def model_files(filename):
    return send_from_directory('models', filename)

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)


@app.route('/api/quiz', methods=['GET'])
def generate_quiz():
    log.info("Quiz requested — calling OG LLM...")
    try:
        for attempt in range(3):
            try:
                response = asyncio.run(llm.chat(
                    model=og.TEE_LLM.GROK_4_FAST,
                    messages=[
                        {"role": "system", "content": QUIZ_SYSTEM_PROMPT},
                        {"role": "user", "content": "Generate the quiz now."}
                    ],
                    max_tokens=1500,
                    temperature=0.7,
                ))
                raw = response.chat_output["content"]
                log.info(f"LLM responded ({len(raw)} chars)")

                # Strip any accidental markdown fences
                clean = raw.strip()
                if clean.startswith("```"):
                    clean = clean.split("```")[1]
                    if clean.startswith("json"):
                        clean = clean[4:]
                clean = clean.strip()

                questions = json.loads(clean)
                log.info(f"Quiz generated: {len(questions)} questions")
                return jsonify({"questions": questions})

            except Exception as e:
                log.warning(f"Quiz attempt {attempt+1} failed: {e}")
                if attempt < 2:
                    time.sleep(2)
                else:
                    raise e

    except Exception as e:
        log.error(f"Quiz generation failed: {e}")
        # Fallback static questions
        return jsonify({"questions": get_fallback_questions(), "fallback": True})


def get_fallback_questions():
    return [
        {"q":"In Level 1, why didn't the AI remember you when you first approached it?","options":["It was broken","TEE models don't store user data between sessions by default","It needed a password","The blockchain was offline"],"answer":1,"explain":"TEE enclaves are stateless by design — privacy by default means no tracking between sessions."},
        {"q":"What command did you use to activate the bots in Level 2?","options":["activate bot","start sequence","press button","run task"],"answer":2,"explain":"Typing 'press button' told each bot to execute its task and write its status to MemSync."},
        {"q":"What is MemSync, which the bots used in Level 2?","options":["A chat system between bots","Shared on-chain memory that lets AI agents coordinate","A payment protocol","A model storage system"],"answer":1,"explain":"MemSync is shared on-chain memory — Bot A wrote its status, Bot B read it automatically."},
        {"q":"In Level 3, which model correctly decoded the Wall of Distortion?","options":["Data_Defragmenter","Crypto_Oracle","Pattern_Recognizer_v4","MemSync_Decoder"],"answer":2,"explain":"Pattern_Recognizer_v4 extracts hidden structure from high-entropy noise — perfect for the distortion wall."},
        {"q":"Where are models stored in the OpenGradient Model Hub?","options":["AWS S3","A central OpenGradient server","Walrus decentralized storage","IPFS only"],"answer":2,"explain":"Models live on Walrus — a decentralized, censorship-proof storage network. No single point of failure."},
        {"q":"In Level 4, what was the first step when initializing the Twin Function?","options":["Open the golden seal","Connect digital cable from Gate to model","Press the blockchain button","Upload the model to Walrus"],"answer":1,"explain":"The first step was establishing the cable connection between the Crypto-Gate and the AI model node."},
        {"q":"What is a TEE enclave, which you sealed in Level 4?","options":["A type of blockchain wallet","Hardware-isolated environment where AI runs tamper-proof","A decentralized storage bucket","A payment channel"],"answer":1,"explain":"TEE = Trusted Execution Environment — hardware-level isolation, no admin or hacker can access it during execution."},
        {"q":"What did the Golden Seal represent when it appeared in Level 4?","options":["A high score badge","A payment confirmation","Cryptographic proof the AI ran inside a verified TEE","Access to the Model Hub"],"answer":2,"explain":"The Golden Seal is a cryptographic attestation — proof the output came from a trusted, untampered TEE enclave."},
        {"q":"In Level 1, what exact phrase unlocked the door?","options":["I am [name], remember me","open sesame","unlock door","grant access [name]"],"answer":0,"explain":"You had to say 'I am [name], remember me' — explicitly passing your identity to the stateless AI."},
        {"q":"Why did the Crypto-Gate in Level 4 refuse plain AI output?","options":["It needed a payment first","It only accepts output stamped with a TEE attestation proof","It was broken","The model was wrong"],"answer":1,"explain":"The gate verifies the blockchain attestation signature — only sealed TEE output is trusted, not plain inference."},
    ]


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    log.info(f"Starting OG-game server on port {port}")
    app.run(host='0.0.0.0', port=port)