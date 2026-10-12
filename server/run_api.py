"""Spawn-safe launcher for the private API. Does not start services on import."""
if __name__ == "__main__":
    import multiprocessing
    import uvicorn
    multiprocessing.freeze_support()
    uvicorn.run("main:app", host="127.0.0.1", port=8321, log_level="info")
