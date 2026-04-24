# Bolt Food — Streamlit team dashboards (Boltable / container hosts)
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY smart_promo ./smart_promo
COPY databricks-setup ./databricks-setup
COPY .streamlit ./.streamlit
COPY team_food_dashboards.py smart_promo_app.py ./

ENV STREAMLIT_SERVER_HEADLESS=true

EXPOSE 8501

# Many hosts set PORT; default 8501 for local `docker run -p 8501:8501`.
ENTRYPOINT ["sh", "-c", "exec streamlit run team_food_dashboards.py --server.address=0.0.0.0 --server.port=${PORT:-8501}"]
