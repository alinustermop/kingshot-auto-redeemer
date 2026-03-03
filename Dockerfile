# Use a lightweight Python 3.11 image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the bot's code into the container
COPY . .

# Create the data folder where the DB and logs will be stored
RUN mkdir -p /app/data

# Run the Discord Manager as the main entry point
CMD ["python", "Discord_Manager.py"]