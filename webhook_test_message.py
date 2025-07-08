import pika
import json

params = pika.ConnectionParameters(
    host='localhost',
    port=5672,
    credentials=pika.PlainCredentials(
        'guest',
        'guest'
    )
)
conn = pika.BlockingConnection(params)
channel = conn.channel()
channel.queue_declare(queue='high_priority', durable=True)
event = {
    "event_name": "subscriber_created",
    "event_time": "2025-07-07T18:02:00+07:00",
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
channel.basic_publish(
    exchange='',
    routing_key='high_priority',
    body=json.dumps(event)
)
conn.close()