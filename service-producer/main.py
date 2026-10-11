import json
import os
import time
import uuid
import dataclasses
from dataclasses import field

import pandas as pd
import pathlib
from kafka import KafkaProducer

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

def _get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Environment variable '{name}' is not set. "
            f"Please export it before running the producer."
        )
    return value


# Конфигурация Producer
@dataclasses.dataclass(frozen=True)
class ProducerConfig:
    kafka_brokers: str = _get_env("KAFKA_BROKERS")
    kafka_topic: str = _get_env("KAFKA_TRANSACTIONS_GROUP_ID")
    data_path: pathlib.Path = field(default=pathlib.Path("./raw_data/train.csv"))


def send_to_kafka(cfg: ProducerConfig):
    """Отправка данных в Kafka с уникальным ID транзакции"""
    producer = KafkaProducer(
        bootstrap_servers=cfg.kafka_brokers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        security_protocol="PLAINTEXT",
    )

    try:
        df = pd.read_csv(cfg.data_path, parse_dates=["transaction_time"]).drop(
            columns=["target"], errors="ignore"
        )
        # имитация того, что транзакции прилетают последовательно,
        # ровно так, как и происходят в реальном мире
        df.sort_values(by="transaction_time", inplace=True)
        df = df.astype(str)

        for row in df.to_dict(orient="records"):
            transaction_id = str(uuid.uuid4())
            message = {"transaction_id": transaction_id, **row}
            producer.send(cfg.kafka_topic, value=message)
            logger.info(f"SENT: {transaction_id=}")
            time.sleep(0.1)

        producer.flush()
    except Exception as e:
        raise ValueError(f"Error while uploading data to Kafka: {e}")
    finally:
        producer.close(timeout=10)


if __name__ == "__main__":
    cfg = ProducerConfig()
    send_to_kafka(cfg)
