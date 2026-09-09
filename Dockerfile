# resume-tailor web app in a container.
# The `claude-cli` provider is NOT available here (no Claude Code binary/login) —
# pick an API provider (OpenAI / Gemini / Anthropic / OpenRouter / …) or point
# `custom` at a model server on your host. PDFs use the built-in renderer
# (no LibreOffice in the image).
FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[api]" \
    && resume-tailor version

ENV RESUME_TAILOR_HOME=/data
VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["resume-tailor", "web", "--host", "0.0.0.0", "--port", "8000"]
