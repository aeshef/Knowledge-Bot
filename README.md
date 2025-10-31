# Knowledge Bot (Obsidian + Telegram)

Quickstart (polling):

1) Environment

- VAULT_PATH: absolute path to your vault (default: /Users/aeshef/Documents/Obsidian Vault)
- TELEGRAM_BOT_TOKEN: your bot token
- TELEGRAM_USER_ID: allowed user id
- DEEPSEEK_API_KEY: DeepSeek API key (optional; if absent, heuristic fallback is used)
- DEEPSEEK_BASE_URL: optional custom base (OpenAI-compatible /chat/completions)

2) Python (recommend 3.12)

Use Python 3.12 to avoid wheels/build issues:
```
# If python3.12 is available
python3.12 -m venv venv && source venv/bin/activate
# Or via pyenv
pyenv local 3.12.7
python -m venv venv && source venv/bin/activate
```

3) Install minimal deps
```
pip install -r "800_Автоматизация/Agent/requirements.txt"
```

(Optional) Later, install extractors (URL/PDF/OCR) after confirming Python 3.12:
```
pip install trafilatura readability-lxml pdfminer.six pillow
# (Optional) PyMuPDF and OCR engines may require system libs and can fail on 3.14
# pip install pymupdf paddleocr pytesseract
```

4) Run (polling)
```
python -m "800_Автоматизация.Agent.knowledge_bot.bot"
```

Batch test (dry-run routing without Telegram)
```
# Prepare a file with lines: free text, URLs, or absolute file paths
echo "https://example.com/article" > /tmp/samples.txt
echo "/Users/you/Downloads/test.pdf" >> /tmp/samples.txt
echo "Идея: сделать X" >> /tmp/samples.txt

# Run (writes under /tmp/notes for dry-run)
python -m "800_Автоматизация.Agent.knowledge_bot.batch_test" /tmp/samples.txt --dry-output /tmp/notes
```

Notes
- Templates are read from `800_Автоматизация/Templates/Clones`.
- Raw files are stored under `700_База_Данных/Export/YYYY/MM/`.
- Attachments under `700_База_Данных/_Вложения/YYYY/MM/`.
