from kraken.server import kraken

def main():
    kraken.run(transport="http", host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()