from kraken.server import kraken

def main():
    try:
        kraken.run(transport="http", host="0.0.0.0", port=8001)
    except KeyboardInterrupt:
        print("Server stopped by user.")