"""Run the four-origin local human demo until interrupted."""
import json
import argparse
import logging
import os
import signal
import threading
from .server import Runtime, RETAILER_IDS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ports', nargs=4, type=int, metavar=('AGGREGATOR', 'NORDBYTE', 'HEMTEKNIK', 'SIGNALBODEN'),
                        help='Stable local demo ports; omitted ports are allocated dynamically.')
    args = parser.parse_args()
    if args.ports and any(not 0 <= port <= 65535 for port in args.ports):
        parser.error('Ports must be between 0 and 65535')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    ports = dict(zip(('aggregator', *RETAILER_IDS), args.ports)) if args.ports else None
    runtime = Runtime(ports=ports)
    done = threading.Event()
    def stop(signum, _frame):
        logging.info('Received signal %s; stopping demo PID %s', signum, os.getpid())
        done.set()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)
    logging.info('Demo started PID %s; state is in memory and resets on restart', os.getpid())
    print(json.dumps(runtime.origins, ensure_ascii=False), flush=True)
    try:
        done.wait()
    finally:
        runtime.close()
        logging.info('Demo stopped PID %s', os.getpid())


if __name__ == "__main__":
    main()
