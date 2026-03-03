# Kingshot Auto-Redeemer
An automated ETL and state management tool for managing and redeeming promotional gift codes for the game Kingshot.
## Key Features:
* **Multi-Account Orchestration**: Utilizes a queue-based system to manage and process multiple player profiles within a single execution cycle.
* **Automated Data Retrieval**: Programmatically interfaces with external APIs to fetch active promotional codes and validate player account data.
* **State-Persistent Storage**: Leverages a relational SQLite backend to track redemption history per player, ensuring data integrity and preventing redundant requests.
* **Operational Monitoring**: Features a structured logging system to track API responses, successful redemptions, and system errors in real-time.
* **Resiliency & Rate Control**: Implements configurable request delays and error-threshold pausing to ensure system stability and compliance with API limitations.
## Tech Stack:
* **Language**: Python 3.x
* **Storage**: SQLite (Relational Database)
* **Libraries**: `requests` (API interaction), `hashlib` (Security/Signatures), `logging` (Monitoring).
## Security & Configuration
* **Request Signing**: The system uses MD5 hashing for authentication signatures.
* **Note on Sensitive Data**: The SALT required for request signing was discovered through public sources. Out of respect for the service providers, it is not included in this repository. Users must provide their own SALT in the constants.py file.
##  Data Architecture
The system maintains a relational structure to ensure data integrity:
* **Players Table**: Stores unique player identifiers (FID) and nicknames.
* **Redemptions Table**: Tracks specific code successes per player with unique constraints to prevent data duplication.
## Project Structure
* `main.py`: Core orchestration logic and redemption cycle management.
* `API_Manager.py`: Handles HTTP requests, authentication signatures, and API interactions.
* `Database_Manager.py`: Manages the SQLite connection, table schema, and data logging.
## Setup & Usage
1. Clone the repository.
2. Install dependencies: `pip install -r requirements.txt`.
3. Configure `constants.py` based on the provided template.
4. Edit to choose the preferred run option `python main.py` and run the automation.

## Disclaimer
This project is for educational purposes only. Users are responsible for ensuring compliance with the game's terms of service.
