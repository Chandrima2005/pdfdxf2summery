# Deploying

## Hugging Face Spaces (free, recommended)

1. Create a Space at huggingface.co/new-space. Choose **Docker** as the SDK (blank template).
2. Spaces reads its settings from YAML at the top of the Space's README. Keep your GitHub README clean by
   adding this block only in the Space copy (or push to the Space from a branch that has it):

   ```yaml
   ---
   title: CAD Copilot
   emoji: 📐
   colorFrom: blue
   colorTo: gray
   sdk: docker
   app_port: 7860
   ---
   ```

3. Push the code to the Space's git remote:
   ```bash
   git remote add space https://huggingface.co/spaces/<your-username>/cad-copilot
   git push space main
   ```
4. In the Space's **Settings → Variables and secrets**, add `LLM_PROVIDER` (variable) and your API key
   (secret, `OPENAI_API_KEY`), plus `OPENAI_BASE_URL` and `LLM_MODEL`. Without them the app runs in offline mode.

The first build takes several minutes (it installs CPU PyTorch and downloads the embedding model).

**Cost warning:** a public Space with your API key lets anyone spend your credits. Either keep the Space
private while sharing the link selectively, set a spending limit on your API account, or deploy the public
version in offline mode and show LLM results in the README and demo GIF.

## Any Python host (Render, Railway, a VM)

Install `requirements.txt` and start `uvicorn app.server:app --host 0.0.0.0 --port $PORT`. It uses TF-IDF
retrieval; add `sentence-transformers` if you want dense embeddings and the host has the memory.
Set `OPENAI_API_KEY`, `OPENAI_BASE_URL` (e.g. `https://openrouter.ai/api/v1`) and `LLM_MODEL` as environment variables.

## Docker locally

```bash
docker build -t cad-copilot .
docker run -p 7860:7860 --env-file .env cad-copilot   # http://localhost:7860
```
