from locust import HttpUser, task, between
import pika
import json

class RabbitMQProducer(HttpUser):
    wait_time = between(1, 5)
    def on_start(self):
        self.params = pika.ConnectionParameters(
            host='localhost',
            port=5672,
            credentials=pika.PlainCredentials(
                'guest',
                'guest'
            )
        )
        self.conn = pika.BlockingConnection(self.params)
        self.channel = self.conn.channel()
        self.channel.queue_declare(
            queue='webhook_events',
            durable=True,
            arguments={'x-max-priority': 2}
        )

    @task
    def publish_high_priority(self):
        event = {
            "event_name": "subscriber_created",
            "event_time": "2025-07-08T13:47:00+07:00",
            "subscriber": {
                "id": "123",
                "status": "active",
                "email": "test@example.com"
            },
            "segment": {
                "id": "seg1",
                "name": "Segment 1"
            },
            "webhook_id": "wh1"
        }
        self.channel.basic_publish(
            exchange='',
            routing_key='high_priority',
            body=json.dumps(event)
        )

    def on_stop(self):
        self.conn.close()