# LIFEGAME

## Email notifications

LIFEGAME sends only three notification types: an immediate email after a new task is created, one 7:00 AM Asia/Kolkata briefing, and one 10:00 PM Asia/Kolkata progress report. Task difficulty is used as priority, and the task's scheduled date is used as its due date. The current task model has no due-time field, so emails state that no due time is set.

### Configure Gmail SMTP

1. Create a Google App Password for the Gmail account that will send LIFEGAME mail.
2. Put your credentials in the root `.env` file. `.env` is excluded from Git:

   ```dotenv
   EMAIL_HOST=smtp.gmail.com
   EMAIL_PORT=587
   EMAIL_USE_TLS=True
   EMAIL_HOST_USER=you@gmail.com
   EMAIL_HOST_PASSWORD=abcdefghijklmnop
   DEFAULT_FROM_EMAIL=you@gmail.com
   EMAIL_NOTIFICATION_TO=you@gmail.com
   ```

   Gmail displays App Passwords in groups; enter its 16 characters without spaces. `DEFAULT_FROM_EMAIL` and `EMAIL_NOTIFICATION_TO` can both be the Gmail address above. If `EMAIL_NOTIFICATION_TO` is blank, it defaults to `EMAIL_HOST_USER`. Never commit `.env` or put the password in a template or JavaScript file.

3. Install dependencies and migrate:

   ```sh
   pip install -r requirements.txt
   python manage.py migrate
   ```

4. Verify configuration and send a real test email:

   ```sh
   python manage.py send_lifegame_test_email
   # Or specify a different recipient:
   python manage.py send_lifegame_test_email recipient@example.com
   ```

   This command validates the settings and sends through Gmail SMTP. A successful SMTP response confirms Gmail accepted the message; inbox delivery still depends on the recipient's mail provider and spam filters.

### Start automatic reports

Run the scheduler as a separate, continuously running process against the same persistent database as the web application:

```sh
python manage.py run_email_scheduler
```

Keep it alive with your process manager (for example systemd or Supervisor) using automatic restart on failure. Run one web service and one scheduler service; both need the same `.env` variables and database. The scheduler checks every 20 seconds, stores report executions and a single-instance lease in the Django database, sends that day's report if its scheduled time has passed while the worker was restarting, and retries temporary send failures with backoff. Do not start the scheduler from `AppConfig.ready()` or from each web worker. If your host cannot keep a worker running, configure its cron service to run `python manage.py run_email_scheduler --once` every minute; this one-shot mode takes the same database lease before checking for due reports.

The database's unique constraints prevent more than one morning or nightly report per date, including across restarts and concurrent scheduler starts. A report is marked sent only after Django's SMTP backend accepts it. Failed sends and attempt counts are visible in Django admin under **Email notifications**.

### Manual report and retry commands

These do not configure or start the scheduler:

```sh
python manage.py send_lifegame_report morning
python manage.py send_lifegame_report nightly
python manage.py send_lifegame_report morning --date 2026-11-22
python manage.py send_lifegame_report nightly --retry
```

Each report command uses actual task and completion records. It skips a manual report already marked sent for that date; manual test reports are tracked separately and do not consume the scheduled report's daily send. `--retry` retries a failed manual report immediately.

### Data and privacy

Task creation has an idempotency key in the built-in form and API client. A retried request returns the original task and does not send a second new-task message. Editing, completing, archiving, or viewing tasks does not send mail. Nightly completion totals are calculated from `TaskCompletion.completed_at` in the configured Asia/Kolkata timezone.

SMTP credentials are read from environment variables and never included in email logs. Notification rows retain type, related task/report date, status, attempt count, SMTP failure details, and sent time. The test-email command sends a test message but does not create a notification record.
