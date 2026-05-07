# 🤖 Redshift Chatbot — Local Dev → AWS Production

Natural language data chatbot. Ask questions in plain English, get SQL + answers.

**Local stack (free):** Ollama (LLM) + PostgreSQL (Docker)  
**AWS stack (production):** Bedrock Claude + Redshift Data API

---

## 🚀 Quick Start (5 steps)

### 1. Install Docker & Ollama
- Docker: https://docker.com/products/docker-desktop
- Ollama: https://ollama.ai

### 2. Start PostgreSQL
```bash
docker run -d \
  --name local-redshift \
  -e POSTGRES_USER=admin \
  -e POSTGRES_PASSWORD=admin123 \
  -e POSTGRES_DB=datawarehouse \
  -p 5432:5432 \
  postgres:15
```

### 3. Pull LLM model
```bash
ollama pull llama3.2
ollama serve
```

### 4. Install Python deps & load data
```bash
pip install -r requirements.txt
python scripts/load_sample_data.py
```

### 5. Launch notebooks
```bash
jupyter notebook notebooks/
```

---

## 📓 Notebooks

| Notebook | Purpose |
|---|---|
| `01_test_connection.ipynb` | Verify DB + Ollama are working |
| `02_chatbot.ipynb` | Interactive Q&A chatbot |
| `03_aws_migration.ipynb` | Switch to Bedrock + Redshift |

---

## 📁 Project Structure

```
redshift-chatbot/
├── .env                          # Config (DB creds, model settings)
├── requirements.txt              # Python dependencies
├── src/
│   ├── db.py                     # DB connector (local + AWS)
│   └── llm.py                    # LLM connector (Ollama + Bedrock)
├── notebooks/
│   ├── 01_test_connection.ipynb
│   ├── 02_chatbot.ipynb
│   └── 03_aws_migration.ipynb
├── scripts/
│   └── load_sample_data.py       # Load sample data into PostgreSQL
└── logs/                         # App logs
```

---

## 🔄 Switching to AWS (3 env var changes)

Edit `.env`:
```bash
DB_MODE=aws           # was: local
LLM_MODE=aws          # was: local

AWS_REGION=us-east-1
REDSHIFT_CLUSTER_ID=your-cluster-id
REDSHIFT_DB=your_database
REDSHIFT_DB_USER=your_user
BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
```

No code changes needed. Open `03_aws_migration.ipynb`.

---

## 💬 Sample Questions to Try

- "How many total bookings do we have?"
- "What are the top 5 cities by number of properties?"
- "What is the total revenue from completed bookings?"
- "Which property category gets the highest average rating?"
- "Show me monthly booking counts for 2023"
- "How many users signed up each month?"

---

## 🛠 Troubleshooting

| Problem | Fix |
|---|---|
| `psycopg2 connection refused` | Run `docker ps` — is PostgreSQL container running? |
| `ollama connection error` | Run `ollama serve` in a terminal |
| `model not found` | Run `ollama pull llama3.2` |
| SQL errors | Check generated SQL in notebook — rephrase question |
| AWS `AccessDeniedException` | Attach `AmazonBedrockFullAccess` + `AmazonRedshiftDataFullAccess` to IAM role |

---

## 💻 System Requirements

- RAM: 8GB minimum (4GB for llama3.2)
- Disk: ~5GB (Docker image + Ollama model)
- OS: Mac / Windows / Linux
