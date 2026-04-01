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
    approval = llm.ensure_opg_approval(opg_amount=4.0)
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

QUIZ_SYSTEM_PROMPT = f"""You are generating a quiz about OpenGradient decentralized AI platform.

Context:
{OG_CONTEXT}

Generate exactly 10 multiple-choice quiz questions. Easy to medium difficulty.

Return ONLY a JSON array, no markdown, no explanation, no backticks. Format:
[
  {{
    "q": "question text",
    "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
    "answer": 0,
    "explain": "one sentence explanation"
  }}
]

"answer" is 0-based index of correct option. Cover: TEE, Walrus, Model Hub, MemSync, Twin Function, x402, ZKML, privacy."""


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

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
        {"q":"What does TEE stand for in OpenGradient?","options":["A) Token Execution Engine","B) Trusted Execution Environment","C) Transparent Encryption Engine","D) Timed Execution Event"],"answer":1,"explain":"TEE = Trusted Execution Environment — hardware-isolated area for secure computation."},
        {"q":"Where are AI models stored in OpenGradient?","options":["A) AWS S3","B) IPFS only","C) Walrus decentralized storage","D) A central server"],"answer":2,"explain":"Models live on Walrus, a censorship-proof decentralized storage network."},
        {"q":"What is a Twin Function?","options":["A) Running two models simultaneously","B) A model wrapped in TEE with cryptographic proof output","C) A function that duplicates data on-chain","D) A backup inference system"],"answer":1,"explain":"Twin Function seals model execution inside a TEE and attaches attestation proof to the output."},
        {"q":"What does the Golden Seal represent?","options":["A) A premium badge","B) Cryptographic attestation proving output came from a trusted TEE","C) A Walrus storage confirmation","D) An x402 payment receipt"],"answer":1,"explain":"The Golden Seal is a cryptographic attestation — proof the model ran inside a verified TEE enclave."},
        {"q":"What is MemSync used for?","options":["A) Storing model weights","B) Synchronising memory between multiple AI agents on-chain","C) Encrypting user data","D) Paying for inference"],"answer":1,"explain":"MemSync lets multiple AI bots coordinate by sharing state via blockchain transactions."},
        {"q":"What is the x402 protocol?","options":["A) A ZK proof standard","B) A consensus algorithm","C) A pay-per-inference micropayment protocol","D) A model compression format"],"answer":2,"explain":"x402 enables micro-transactions per model call — no API keys or subscriptions needed."},
        {"q":"What is ZKML?","options":["A) A model training framework","B) Zero-Knowledge ML — proving inference correctness without revealing weights","C) A token standard","D) A decentralized marketplace"],"answer":1,"explain":"ZKML uses zero-knowledge proofs to verify model output without exposing the model weights."},
        {"q":"Why does a TEE model not remember you between sessions?","options":["A) Too expensive","B) Privacy by design — models don't persist user data","C) Blockchain deletes memory","D) Walrus doesn't support persistent data"],"answer":1,"explain":"TEE enclaves are stateless by design — users control their own state and pass it explicitly."},
        {"q":"What makes Walrus storage censorship-proof?","options":["A) Government encryption","B) Single hardened server","C) Distributed across decentralized network with no single point of failure","D) Only verified developers can delete"],"answer":2,"explain":"Walrus distributes model blobs across a decentralized network — no entity can remove them."},
        {"q":"What is VANILLA inference mode?","options":["A) A flavoured model variant","B) Standard inference without cryptographic proof — cheaper but unverified","C) Inference with ZKML proof","D) TEE-only execution"],"answer":1,"explain":"VANILLA mode is standard inference without attestation — faster and cheaper, but not verifiable."},
    ]


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    log.info(f"Starting OG-game server on port {port}")
    app.run(host='0.0.0.0', port=port)
