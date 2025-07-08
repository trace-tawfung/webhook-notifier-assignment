# Webhook Notification System Design

## High-Level Architecture

```
+---------------------+       +-------------------+      +-------------------+
|   RabbitMQ          |       |   Webhook Notifier|      |   Postgres DB     |
|   (Message Broker)  |       |   (Python App)    |      |  (Webhook Configs)|
|                     |       |                   |      |                   |
|  +-------------+    |       |  +------------+   |      |  +-------------+  |
|  | high_priority|   |<----->|  | Worker 1   |   |<---->|  | webhooks    |  |
|  +-------------+    | AMQP  |  +------------+   | SQL  |  +-------------+  |
|  | medium_priority| |<----->|  | Worker 2   |   |      |                   |
|  +-------------+    |       |  +------------+   |      |                   |
|  | low_priority |   |<----->|  | Worker 3   |   |      |                   |
|  +-------------+    |       |  +------------+   |      |                   |
+---------------------+       |                   |      +-------------------+
                              |  +-------------+  |
                              |  | Prometheus  |  |<----> HTTP (port 9090)
                              |  | Metrics     |  |
                              |  +-------------+  |
                              |                   |
                              |  +-------------+  |
                              |  | HTTP Client |  |<-----> HTTP (Webhook URLs)
                              |  +-------------+  |
                              +-------------------+
```

## Component Overview

### 1. RabbitMQ (Message Broker)
- Hosts three durable queues (high_priority, medium_priority, low_priority)
for event prioritization.
- External producers publish JSON events to these queues.

### 2. Webhook Notifier
- A Python application with three worker threads, each consuming from one
queue using `pika.SelectConnection` over AMQP (port 5672).

### 3. Postgres DB
- Stores webhook configurations `(id, post_url, events)` in the webhooks
table, queried via SQL.

### 4. Prometheus Metrics
- Exposes performance and latency metrics on port `9090` for monitoring.

### 5. HTTP Client
- HTTP Client: Sends POST requests to external webhook URLs retrieved from
Postgres

## Technologies Used

- **Python 3.11+**: Main programming language
- **RabbitMQ**: Message queue and caching
- **PostgreSQL**: Webhook configuration storage
- **Prometheus**: Metrics collection

## Database Schema

### webhooks table
```sql
CREATE TABLE webhooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_url TEXT NOT NULL,
    events TEXT[] NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

## Solution Description
The Webhook Notifier is a Python-based system designed to process events
from RabbitMQ queues, retrieve webhook configurations from a Postgres
database, and send HTTP POST requests to configured URLs. It addresses
reliability, scalability, and fairness as follows: 

### Reliability:
- RabbitMQ connections include retries (
`connection_attempts=3, retry_delay=5`) for network failures.
- HTTP requests use exponential backoff (1s, 2s, 4s, 8s, 16s) for up to
5 attempts.
- Failed messages are requeued (`basic_nack`) to prevent data loss.
- Explicit connection cleanup ensures graceful shutdown

### Scalability:
- Multiple worker threads process queues concurrently,
and additional instances can be deployed for horizontal scaling.
- RabbitMQ’s queue-based architecture distributes load across workers.

### Fairness:
- Three priority queues ensure smaller accounts (e.g., `high_priority`)
are processed faster than larger accounts (e.g., `low_priority`).
- QoS settings (`prefetch_count=1`) prevent any queue from monopolizing
resources.

### Monitoring:
- Prometheus metrics track event processing latency (
`webhook_event_processing_seconds`) and HTTP request outcomes (
- `webhook_request_success_total`, `webhook_request_failure_total`).
