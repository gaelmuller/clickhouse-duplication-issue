import threading
from datetime import datetime
from random import randint
from threading import Thread
from time import sleep
from uuid import uuid4

from clickhouse_driver import Client

BATCH_SIZE = 1000


def init_database():
    clickhouse = Client(host="localhost", port=9000, user="user", password="plop")

    # Remove previous tables, if they exist
    clickhouse.execute("CREATE DATABASE IF NOT EXISTS test ON CLUSTER test_cluster")
    clickhouse.execute("DROP TABLE IF EXISTS test.counts ON CLUSTER test_cluster SYNC")
    clickhouse.execute(
        "DROP TABLE IF EXISTS test.counts_buffer ON CLUSTER test_cluster SYNC"
    )
    clickhouse.execute(
        "DROP TABLE IF EXISTS test.counts_local ON CLUSTER test_cluster SYNC"
    )

    # Create the local tables
    clickhouse.execute(
        """
    CREATE TABLE test.counts_local ON CLUSTER test_cluster
    (
        `uuid` UUID,
        `count` SimpleAggregateFunction(sum, UInt64),
        `created_at` DateTime
    )
    ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/{shard}/test/counts_local', '{replica}')
    ORDER BY (
        uuid,
        created_at
    )
    """
    )

    # Add a buffer table in front of them
    clickhouse.execute(
        """
    CREATE TABLE test.counts_buffer ON CLUSTER test_cluster (
        `uuid` UUID,
        `count` SimpleAggregateFunction(sum, UInt64),
        `created_at` DateTime
    )
    ENGINE = Buffer('test', 'counts_local', 1, 1, 1, 0, 500000, 0, 100000000)
    """
    )

    # Add a distributed table pointing to the buffer tables
    clickhouse.execute(
        """
    CREATE TABLE test.counts ON CLUSTER test_cluster (
        `uuid` UUID,
        `count` SimpleAggregateFunction(sum, UInt64),
        `created_at` DateTime
    )
    ENGINE = Distributed('test_cluster', 'test', 'counts_buffer', rand())
    """
    )


def send_count_batch(batch_size: int) -> list:
    """Create a batch of random counts and send it to ClickHouse. Return the batch."""
    clickhouse = Client(host="localhost", port=9000, user="user", password="plop")

    batch = []
    for _ in range(batch_size):
        batch.append(
            (
                str(uuid4()),
                randint(1, 5),
                datetime(2024, 2, 19, 10, 42),
            )
        )

    clickhouse.execute(
        "INSERT INTO test.counts (`uuid`, `count`, `created_at`) VALUES",
        batch,
    )

    return batch


class LoadThread(Thread):
    def __init__(self):
        super().__init__()
        self._should_stop = threading.Event()
        self._rows = 0

    def run(self):
        while not self._should_stop.is_set():
            send_count_batch(BATCH_SIZE)
            self._rows += BATCH_SIZE

    def stop(self):
        print(f"Stopping load thread, sent a total of {self._rows} rows ...")
        self._should_stop.set()


if __name__ == "__main__":
    # Initialize the database
    init_database()
    print("Initialized the database")

    # Start a thread to simulate a continuous load
    load_thread = LoadThread()
    load_thread.start()
    print("Putting some load on the table in the background...")

    # Send another batch of counts and verify that the counts are correct
    sleep(5)
    batch = send_count_batch(BATCH_SIZE)
    print("Sent the control batch, sleeping for 5 seconds...")
    sleep(5)
    print("Waking up and checking the counts...")
    clickhouse = Client(host="localhost", port=9000, user="user", password="plop")
    for uuid, count, created_at in batch:
        click_count = clickhouse.execute(
            "SELECT sum(count) FROM test.counts WHERE uuid = %(uuid)s",
            {"uuid": uuid},
        )[0][0]

        if click_count != count:
            print("Different count", uuid, count, click_count)

    # Stop the load thread
    load_thread.stop()
    load_thread.join()
