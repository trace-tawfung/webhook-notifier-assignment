# Webhook Notifier

## Solution
#### Solution, system design and technology used is in this file: [webhook_system_design.md](https://github.com/trace-tawfung/webhook-notifier-assignment/blob/master/webhook_system_design.md)

## Implementation

### 1. Install `Python`, `RabbitMQ`, `Prometheus`, `Postgres DB`

### 2. Config Prometheus to scrape endpoint:
```yaml
scrape_configs:
  - job_name: 'webhook_notifier'
    static_configs:
      - targets: ['localhost:9090']
```

### 3. Setup DB schema examples:
```sql
CREATE TABLE webhooks (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid(),
    post_url TEXT NOT NULL,
    events TEXT[] NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO webhooks (id, post_url, events)
VALUES ('wh1', 'http://example.com/webhook', ARRAY['event1']);
```

### 4. Run and test the Notifier
- Run the Notifier:
```bash
pip install -r requirements.py
python webhook_notifier.py
```
- Publish test message:
```bash
python webhook_test_message.py
```
- Benchmarking: Access `http://localhost:8089` to simulate multiple
users publishing events
```bash
locust -f webhook_benchmark_test_message.py --host=http://localhost
```

### 5. Verify Metrics
- Check `http://localhost:9090/metrics` for queue length, event latency,
and priority processing metrics.
- Use RabbitMQ management (`http://localhost:15672`) to monitor queue
activity. 
