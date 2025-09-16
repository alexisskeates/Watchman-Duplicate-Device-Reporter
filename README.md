# Watchman Duplicate Device Reporter

A Python script that identifies and reports duplicate devices in Watchman Monitoring based on System MAC Address. The script generates detailed reports showing which devices should be kept (most recent activity) and which should be removed (older duplicates).

> **Note:** This script was developed with the assistance of AI to provide robust duplicate detection and reporting capabilities for Watchman Monitoring environments.

## Features

- 🔍 **Duplicate Detection** - Finds devices with identical System MAC addresses
- 📊 **Smart Prioritization** - Keeps devices with the most recent report dates
- 📧 **Email Reports** - Automatically sends HTML + text email reports (only when duplicates found)
- 📄 **CSV Export** - Export detailed reports to CSV files
- 🔧 **Easy Configuration** - Interactive setup with `.env` file management
- 🤖 **Automation Ready** - Silent mode perfect for cron jobs
- 🛡️ **Safe Operation** - Read-only API calls, manual removal required

## Why This Script Exists

The Watchman Monitoring API doesn't support automatic device deletion, and duplicate devices can clutter your monitoring dashboard. This script helps you:

- Identify duplicate devices that share the same MAC address
- Determine which duplicates to keep based on most recent activity
- Get direct links to each device for easy manual removal
- Automate duplicate monitoring with email alerts

## Requirements

- Python 3.6+
- Ubuntu/Linux server (tested on Ubuntu 24.04 LTS)
- Watchman Monitoring account with API access
- SMTP email account (optional, for email reports)

## Installation

1. **Clone the repository:**
   ```bash
   git clone <your-repo-url>
   cd watchman-duplicate-reporter
   ```

2. **Install Python dependencies:**
   ```bash
   pip3 install requests
   ```

3. **Make the script executable:**
   ```bash
   chmod +x watchman_duplicate_check.py
   ```

## Configuration

### First Run Setup

The script will automatically guide you through configuration on first run:

```bash
python3 watchman_duplicate_check.py
```

This creates a `.env` file with your credentials:

```env
# Watchman API Settings (Required)
WATCHMAN_SUBDOMAIN=your_subdomain
WATCHMAN_API_KEY=your_api_key

# Email Settings (Optional) - SMTP2GO Example
SMTP_SERVER=mail.smtp2go.com
SMTP_PORT=587
SMTP_USERNAME=your-smtp2go-username
SMTP_PASSWORD=your-smtp2go-password
EMAIL_FROM=monitoring@yourcompany.com
EMAIL_TO=admin@company.com
SMTP_USE_TLS=true
```

### Email Provider Setup

#### SMTP2GO (Recommended)
[SMTP2GO](https://www.smtp2go.com/) is a reliable transactional email service that's perfect for automated scripts:

1. **Create SMTP2GO Account:** Sign up at [smtp2go.com](https://www.smtp2go.com/)
2. **Get SMTP Credentials:** Go to Settings → SMTP Users → Create SMTP User
3. **Configuration:**
   ```env
   SMTP_SERVER=mail.smtp2go.com
   SMTP_PORT=587
   SMTP_USERNAME=your-smtp2go-username
   SMTP_PASSWORD=your-smtp2go-password
   SMTP_USE_TLS=true
   ```
4. **Benefits:**
   - Dedicated for transactional emails
   - High deliverability rates
   - Detailed analytics and logs
   - Free tier available (1,000 emails/month)

## Usage

### Basic Commands

```bash
# Generate report (automatically emails if duplicates found)
python3 watchman_duplicate_check.py

# Export to CSV and send email
python3 watchman_duplicate_check.py --export-csv

# Disable email sending
python3 watchman_duplicate_check.py --no-email

# Reset configuration
python3 watchman_duplicate_check.py --reset-env
```

### Command Line Options

| Option | Description |
|--------|-------------|
| `--export-csv` | Export report to CSV file |
| `--csv-filename FILE` | Specify CSV filename (default: `watchman_duplicates_report.csv`) |
| `--no-email` | Disable automatic email sending |
| `--email-only` | Send email only, suppress console output (for cron jobs) |
| `--reset-env` | Reset .env file with new credentials |
| `--subdomain DOMAIN` | Override subdomain from .env file |
| `--api-key KEY` | Override API key from .env file |
| `--verbose` | Enable verbose output |

### Automation with Cron

Set up automated duplicate checking:

```bash
# Edit crontab
crontab -e

# Check for duplicates every Monday at 9 AM
0 9 * * 1 /usr/bin/python3 /path/to/watchman_duplicate_check.py --email-only --export-csv

# Daily check at 6 AM (silent unless duplicates found)
0 6 * * * /usr/bin/python3 /path/to/watchman_duplicate_check.py --email-only
```

## Sample Output

### Console Report
```
🎯 Watchman Duplicate Device Report
==================================================
📧 Email will be sent to: admin@company.com

📊 Analyzing 150 computers for duplicates...

🔍 MAC Address: a45e60cf276b
----------------------------------------
   ✅ KEEP: EAST-MAIN-PC (20240315-XYZW-123456)
      Last Report: 2024-03-15T10:30:00
      Serial: ABC123DEF456
      OS: Windows 11 Pro
      URL: https://company.monitoringclient.com/computers/...

   ❌ REMOVE: EAST-OLD-PC (20230217-AFPI-0XGAWE)
      Last Report: 2023-02-17T08:15:00
      Serial: ABC123DEF456
      OS: Windows 10 Pro
      URL: https://company.monitoringclient.com/computers/...
      Reason: Older report date than keeper
```

### Email Report Features
- **HTML formatting** with color-coded keep/remove indicators
- **Direct links** to each computer in Watchman dashboard
- **CSV attachment** with detailed device information
- **Summary statistics** and clear next steps

## Email Behavior

| Scenario | Email Sent? | Console Message |
|----------|-------------|----------------|
| Duplicates found + Email configured | ✅ Yes | "Email report sent successfully!" |
| No duplicates found | ❌ No | "No email sent - no duplicates to report" |
| Email not configured | ❌ No | "Email not configured - report will only be displayed" |
| `--no-email` flag used | ❌ No | "Email disabled with --no-email flag" |

## How It Works

1. **Fetches all computers** from your Watchman account via API
2. **Groups devices** by System MAC Address (normalized)
3. **Identifies duplicates** within each MAC address group
4. **Sorts by last report date** - newest first
5. **Marks for action:**
   - **KEEP**: Device with most recent activity
   - **REMOVE**: Older devices with same MAC
6. **Generates reports** in console, email, and CSV formats
7. **Sends email alerts** only when duplicates are found

## Manual Removal Process

Since the Watchman API doesn't support device deletion:

1. **Run this script** to identify duplicates
2. **Click the device URLs** in the report to navigate to each device
3. **Use Watchman's web interface** to manually remove devices marked as "REMOVE"
4. **Keep devices marked as "KEEP"** (most recent activity)

## Security Notes

- **Secure your `.env` file:** `chmod 600 .env`
- **Use App Passwords** for Gmail (not your main password)
- **Consider a dedicated monitoring email account**
- **Add `.env` to `.gitignore`** to avoid committing credentials

## Troubleshooting

### Common Issues

**Syntax Errors:**
```bash
# Check for syntax issues
python3 -m py_compile watchman_duplicate_check.py
```

**API Connection Issues:**
- Verify subdomain and API key in Watchman dashboard
- Check network connectivity to `*.monitoringclient.com`

**Email Issues:**
- Verify SMTP settings with your email provider
- For SMTP2GO, check your account dashboard for usage limits and status
- For Gmail, ensure 2FA is enabled and use App Password
- Test SMTP connectivity: `telnet mail.smtp2go.com 587`

**Permission Issues:**
```bash
# Fix script permissions
chmod +x watchman_duplicate_check.py

# Fix .env permissions
chmod 600 .env
```

## API Rate Limits

The script respects Watchman's API rate limit of 400 requests/minute with automatic backoff.

## File Structure

```
watchman-duplicate-reporter/
├── watchman_duplicate_check.py    # Main script
├── .env                          # Configuration (created on first run)
├── watchman_duplicates_report.csv # Generated CSV report
└── README.md                     # This documentation
```

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Commit your changes: `git commit -am 'Add feature'`
4. Push to the branch: `git push origin feature-name`
5. Submit a pull request

## Acknowledgments

- **AI Development:** This script was created with the assistance of Claude AI to ensure robust functionality and comprehensive error handling
- **Watchman Monitoring:** For providing the API that makes this automation possible
- **SMTP2GO:** For reliable transactional email delivery services

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- **Issues:** Report bugs via GitHub Issues
- **Questions:** Check existing issues or create a new discussion
- **Watchman API:** [Official Documentation](https://api.watchmanmonitoring.com/)

## Changelog

### v1.0.0
- Initial release with duplicate detection and email reporting
- CSV export functionality
- Interactive configuration setup
- Cron-friendly silent mode
