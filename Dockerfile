FROM python:3.10

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5005

CMD [ "python", "./quantum_dashboard.py" ]