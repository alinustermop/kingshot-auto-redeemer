# Kingshot Auto-Redeemer
An automated ETL and state management tool for managing and redeeming gift codes for the game Kingshot.
## Key Features:
* **Automated ETL Pipeline**: Programmatically interfaces with external APIs to fetch active gift codes and validate player account state in real-time.
* **Multi-Account Orchestration**: Implements a queue-based system to manage and process multiple player profiles within a single execution cycle, optimizing request flow and resource allocation.
* **State-Persistent Storage**: Utilizes a relational SQLite backend to track redemption history per player, ensuring transaction integrity, preventing data duplication and redundant requests.
* **Operational Monitoring and Analytics**: Features a structured logging system and a Discord-based dashboard to track API responses, successful redemptions, and system errors in real-time.
* **Resiliency & Rate Control**: Includes configurable request delays and error-threshold pausing to ensure system stability and compliance with API limitations.
* **Cloud Infrastructure**: Containerized with Docker and deployed on Google Cloud Platform (GCP) to ensure high availability and persistent data storage via mounted volumes.
## Tech Stack:
* **Language**: Python 3.11
* **Interface**: Discord API (discord.py)
* **Storage**: SQLite (Relational Database)
* **Infrastructure**: Docker & Docker Compose for containerization.
* **Cloud**: Google Cloud Platform (GCP) for deployment and hosting.
* **Libraries**: `requests` (API interaction), `hashlib` (MD5 Request Signing), `logging` (Monitoring).
## System Commands:
The system is managed through a suite of slash commands for real-time data management via Discord-bot:
* **/find [id]**: Search for a player and check if they are in the list
* **/add [id]**: Add a new player to the auto-redeem list
* **/delete [id]**: Remove a player from the list
* **/history [id]**: See which codes a player has already used
* **/list**: Show all registered players (Admins only)
* **/stats**: Show bot statistics and last 24h activity
* **/next**: See when the next auto-redemption cycle starts
* **/ping**: Check connection latency
* **/redeem_for [id]**: Redeem all active codes for a player ID
* **/redeem_all**: Trigger a manual sync cycle (Owner only)
* **/logs**: View recent bot activity logs (Owner only)
## Security & Configuration
* **Request Signing**: The system uses MD5 hashing for authentication signatures.
* **Configuration**: Sensitive data, including the Discord token and API SALT, must be provided in a constants.py file based on the provided template.
* **Note on Sensitive Data**: The SALT required for request signing was discovered through public sources. Out of respect for the service providers, it is not included in this repository. Users must provide their own SALT in the constants.py file.
##  Data Architecture
The system maintains a relational structure to ensure data integrity:
* **Players Table**: Stores unique player identifiers (FID) and nicknames.
* **Redemptions Table**: Tracks specific code successes per player with unique constraints to prevent data duplication.
## Project Structure
* `main.py`: Core orchestration logic and redemption cycle management.
* `API_Manager.py`: Handles HTTP requests, authentication signatures, and API interactions.
* `Database_Manager.py`: Manages the SQLite connection, table schema, and data logging.
* `Discord_Manager.py`: Provides the asynchronous interface for slash commands and schedules the daily 24-hour background redemption task.
## Setup & Usage
**Local usage**:
1. Clone the repository.
2. Install dependencies: `pip install -r requirements.txt`.
3. Configure `constants.py` based on the provided template.
4. Edit to choose the preferred run option in `main.py` (`run_once()` or `run_daily_loop()`) and run the automation.
**Discord Integration**:
* **Existing Instance**: Add the managed bot to your server using the [link](https://discord.com/oauth2/authorize?client_id=1478083799890792448).
**Self-Hosting (Docker/GCP)**:
1. Ensure Docker and Docker Compose are installed.
2. Create your `constants.py` file with your specific `DISCORD_TOKEN` and `SALT`.
3. Build and deploy the container using 
```bash
docker-compose up -d --build

```
4. The system will automatically initialize the SQLite database and log files within the persistent `/app/data` volume.

## Disclaimer
This project is for educational purposes only. Users are responsible for ensuring compliance with the game's terms of service.
