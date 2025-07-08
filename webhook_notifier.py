import json
import logging
import math
import os
import time
from threading import Thread

import pika
import psycopg2
import requests
from dotenv import load_dotenv
from prometheus_client import Histogram, Counter, start_http_server

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Prometheus metrics
# Histogram to track event processing latency (buckets from 0.1s to 1.0s)
EVENT_LATENCY = Histogram('webhook_event_processing_seconds', 'Time to process webhook events', buckets=[0.1 * i for i in range(1, 11)])
# Counters for successful and failed HTTP requests
REQUEST_SUCCESS = Counter('webhook_request_success_total', 'Total successful webhook requests')
REQUEST_FAILURES = Counter('webhook_request_failure_total', 'Total failed webhook requests')


class WebhookEvent:
    """Represents a webhook event parsed from RabbitMQ message."""
    def __init__(self, data):
        """
        Initialize WebhookEvent from JSON data.

        Args:
            data (dict): Parsed JSON data containing event details.

        Attributes:
            event_name (str): Name of the event (e.g., 'subscriber_created').
            event_time (str): Timestamp of the event.
            subscriber (dict): Subscriber details (id, status, email,...).
            segment (dict): Segment details (id, name).
            webhook_id (str): ID of the webhook configuration to use.
        """
        self.event_name = data.get('event_name')
        self.event_time = data.get('event_time')
        self.subscriber = data.get('subscriber', {})
        self.segment = data.get('segment', {})
        self.webhook_id = data.get('webhook_id')

class WebhookConfig:
    """Represents a webhook configuration from the Postgres database."""
    def __init__(self, id, post_url, events):
        """
        Initialize WebhookConfig with database row data.

        Args:
            id (str): Unique identifier for the webhook.
            post_url (str): Webhook URL to send HTTP POST requests to.
            events (str): Associated account ID for prioritization or filtering.
        """
        self.id = id
        self.post_url = post_url
        self.events = events

class Notifier:
    """Handles event processing, webhook configuration retrieval, and HTTP delivery."""
    def __init__(self, db_conn, amqp_params):
        """
        Initialize Notifier with database and RabbitMQ connection parameters.

        Args:
            db_conn (psycopg2.connection): Postgres database connection.
            amqp_params (pika.ConnectionParameters): RabbitMQ connection parameters.
        """
        self.db = db_conn
        self.amqp_params = amqp_params
        # Initialize HTTP session with a 10-second timeout for webhook requests
        self.http_session = requests.Session()
        self.http_session.timeout = 10
        # Track connections for shutdown
        self.connections = []

    def start_worker(self, queue_name):
        """
        Start a worker thread to consume messages from a specific RabbitMQ queue.

        Args:
            queue_name (str): Name of the queue to consume from (e.g., 'high_priority').

        Logic:
            - Creates a new SelectConnection for thread safety.
            - Sets up callbacks for connection, channel, queue declaration, and message consumption.
            - Runs the connection's I/O loop to process messages asynchronously.
        """
        def on_open_connection(connection):
            """Callback when RabbitMQ connection is opened."""
            logger.info(f"Connection opened for queue {queue_name}")
            self.connections.append(connection)
            connection.channel(
                on_open_callback=lambda channel: on_open_channel(
                    channel,
                    queue_name
                )
            )

        def on_open_channel(channel, queue_name):
            """Callback when a channel is opened; declares the queue."""
            logger.info(f"Channel opened for queue {queue_name}")
            channel.queue_declare(
                queue=queue_name,
                durable=True,
                callback=lambda frame: on_queue_declared(
                    channel,
                    queue_name
                )
            )

        def on_queue_declared(channel, queue_name):
            """Callback when queue is declared; sets QoS and starts consuming."""
            try:
                logger.info(f"Queue {queue_name} declared")
                channel.basic_qos(prefetch_count=1)
                channel.basic_consume(queue=queue_name,
                                      on_message_callback=lambda ch, method, props, body: on_message(ch, method, props,
                                                                                                     body, queue_name))
                logger.info(f"Started consuming from queue {queue_name}")
            except Exception as e:
                logger.error(f"Error setting up consumer for queue {queue_name}: {e}")
                channel.connection.close()

        def on_message(channel, method, properties, body, queue_name):
            """
            Callback for processing received messages.

            Logic:
                - Measures processing time for Prometheus metrics.
                - Processes the event (parse JSON, fetch config, send webhook).
                - Acknowledges or rejects the message based on success.
            """
            start_time = time.time()
            try:
                self.process_event(body)
                EVENT_LATENCY.observe(time.time() - start_time)
                channel.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                logger.error(f"Error processing event in queue {queue_name}: {e}")
                channel.basic_nack(
                    delivery_tag=method.delivery_tag,
                    requeue=True
                )

        def on_connection_error(connection, error):
            """Callback for connection errors."""
            logger.error(f"Connection error for queue {queue_name}: {error}")
            connection.ioloop.stop()

        def on_connection_close(connection, reason):
            """Callback for connection is closed."""
            logger.info(f"Connection closed for queue {queue_name}: {reason}")
            connection.ioloop.stop()

        try:
            # Create a new SelectConnection for this worker
            connection = pika.SelectConnection(
                parameters=self.amqp_params,
                on_open_callback=on_open_connection,
                on_open_error_callback=on_connection_error,
                on_close_callback=on_connection_close
            )
            logger.info(f"Starting worker for queue {queue_name}")
            connection.ioloop.start()
        except Exception as e:
            logger.error(f"Failed to start worker for queue {queue_name}: {e}")
            raise

    def process_event(self, body):
        """
        Process a single RabbitMQ message.

        Logic:
            - Parses the message body as JSON to create a WebhookEvent.
            - Retrieves the webhook configuration from Postgres.
            - Sends the event data to the webhook URL.

        Args:
            body (bytes): Raw message body from RabbitMQ.
        """
        try:
            event_data = json.loads(body)
            event = WebhookEvent(event_data)
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse event: {e}")

        config = self.get_webhook_config(event.webhook_id)
        self.send_webhook(config.post_url, event_data)

    def get_webhook_config(self, webhook_id):
        """
        Retrieve webhook configuration from Postgres.

        Args:
            webhook_id (str): ID of the webhook to fetch.

        Returns:
            WebhookConfig: Configuration object with id, url, and account_id.

        Raises:
            Exception: If the webhook is not found or a database error occurs.
        """
        try:
            with self.db.cursor() as cur:
                cur.execute("SELECT id, post_url, events FROM webhooks WHERE id = %s", (webhook_id,))
                result = cur.fetchone()
                if not result:
                    raise Exception(f"Webhook config not found for ID: {webhook_id}")
                return WebhookConfig(*result)
        except psycopg2.Error as e:
            raise Exception(f"Database error: {e}")

    def send_webhook(self, url, event_data):
        """
        Send an HTTP POST request to the webhook URL.

        Logic:
            - Sends the event data as JSON with up to 5 retries.
            - Uses exponential backoff (1s, 2s, 4s, 8s, 16s) for retries.
            - Increments Prometheus counters for success or failure.

        Args:
            url (str): Webhook URL to send the request to.
            event_data (dict): Event data to send as JSON.

        Raises:
            Exception: If all retries fail.
        """
        for attempt in range(5):
            try:
                response = self.http_session.post(
                    url,
                    json=event_data,
                    headers={'Content-Type': 'application/json'}
                )
                if 200 <= response.status_code < 300:
                    REQUEST_SUCCESS.inc()
                    return
                else:
                    REQUEST_FAILURES.inc()
                    logger.warning(f"HTTP request failed with status {response.status_code}")
            except requests.RequestException as e:
                REQUEST_FAILURES.inc()
                logger.warning(f"HTTP request attempt {attempt + 1} failed: {e}")
            time.sleep(math.pow(2, attempt))
        raise Exception("Failed to send webhook after retries")

    def close_connection(self):
        """Close all tracked RabbitMQ connections."""
        for conn in self.connections:
            try:
                if not conn.is_closed:
                    conn.close()
                    conn.ioloop.start()
            except Exception as e:
                logger.error(f"Error closing connection: {e}")


def main():
    """
    Main function to initialize and run the notifier.

    Logic:
        - Starts the Prometheus metrics server on port 9090.
        - Connects to Postgres using environment variables or defaults.
        - Sets up RabbitMQ connection parameters.
        - Creates a Notifier instance and starts worker threads for each queue.
        - Keeps the main thread running until interrupted.
    """
    # Start Prometheus metrics server
    start_http_server(9091)
    logger.info("Prometheus metrics server started on: 9091")

    # Load environment variables from .env file
    load_dotenv()

    # Postgres connection
    try:
        db_conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "dbname"),
            user=os.getenv("DB_USER", "user"),
            password=os.getenv("DB_PASSWORD", "password"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432")
        )
        logger.info("Connected to Postgres")
    except psycopg2.Error as e:
        logger.error(f"Failed to connect to Postgres: {e}")
        raise

    # Configure RabbitMQ connection parameters
    amqp_params = pika.ConnectionParameters(
        host=os.getenv("RABBITMQ_HOST", "localhost"),
        port=int(os.getenv("RABBITMQ_PORT", "5672")),
        credentials=pika.PlainCredentials(
            os.getenv("RABBITMQ_USER", "guest"),
            os.getenv("RABBITMQ_PASSWORD", "guest")
        ),
        connection_attempts=3,
        retry_delay=5
    )

    # Initialize Notifier
    notifier = Notifier(db_conn, amqp_params)
    queues = ['high_priority', 'medium_priority', 'low_priority']

    # Start workers in separate threads
    threads = []
    for queue in queues:
        thread = Thread(
            target=notifier.start_worker,
            args=(queue,),
            daemon=True
        )
        thread.start()
        threads.append(thread)
        logger.info(f"Started worker thread for queue {queue}")

    # Keep main thread running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        notifier.close_connection()
        db_conn.close()
        # Daemon threads will exit automatically

if __name__ == "__main__":
    main()