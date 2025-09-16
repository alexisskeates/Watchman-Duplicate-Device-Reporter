#!/usr/bin/env python3
"""
Watchman Monitoring Duplicate Device Report Script

This script finds and reports on duplicate devices in Watchman Monitoring based on System MAC Address.
It generates a detailed report showing which devices are duplicates and which ones should be kept/removed
based on the most recent report date.

Requirements:
- Python 3.6+
- requests library (pip install requests)

Usage:
1. Create a .env file with your credentials (script will help you create one)
2. Run to generate a comprehensive duplicate devices report
3. Use the report to manually remove duplicates through the Watchman web interface

.env file format:
WATCHMAN_SUBDOMAIN=your_subdomain
WATCHMAN_API_KEY=your_api_key
"""

import requests
import json
import argparse
import sys
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import time

# No external dependencies beyond requests needed

class WatchmanAPI:
    def __init__(self, subdomain: str, api_key: str):
        self.base_url = f"https://{subdomain}.monitoringclient.com/v2.5"
        self.api_key = api_key
        self.session = requests.Session()
        
    def _make_request(self, endpoint: str, method: str = 'GET', params: Dict = None, data: Dict = None) -> Dict:
        """Make API request with error handling and rate limiting"""
        url = f"{self.base_url}/{endpoint}"
        
        # Add API key to params
        if params is None:
            params = {}
        params['api_key'] = self.api_key
        
        try:
            if method == 'GET':
                response = self.session.get(url, params=params)
            elif method == 'DELETE':
                response = self.session.delete(url, params=params)
            elif method == 'PUT':
                response = self.session.put(url, params=params, data=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
                
            # Handle rate limiting (400 requests/minute)
            if response.status_code == 429:
                print("Rate limit hit, waiting 60 seconds...")
                time.sleep(60)
                return self._make_request(endpoint, method, params, data)
            
            response.raise_for_status()
            
            if method == 'DELETE' and response.status_code == 204:
                return {"status": "deleted"}
                
            return response.json()
            
        except requests.exceptions.RequestException as e:
            print(f"API request failed: {e}")
            if hasattr(e.response, 'text'):
                print(f"Response: {e.response.text}")
            sys.exit(1)
    
    def get_all_computers(self) -> List[Dict]:
        """Fetch all computers from Watchman API with pagination"""
        computers = []
        page = 1
        per_page = 100  # Maximum allowed per page
        
        print("Fetching all computers from Watchman API...")
        
        while True:
            print(f"Fetching page {page}...")
            params = {
                'page': page,
                'per_page': per_page,
                'order': 'last_reported_desc'
            }
            
            response = self._make_request('computers', params=params)
            
            if not response or not isinstance(response, list):
                break
                
            computers.extend(response)
            
            # Check if we got fewer results than requested (last page)
            if len(response) < per_page:
                break
                
            page += 1
            
        print(f"Fetched {len(computers)} total computers")
        return computers
    
    def delete_computer(self, computer_uid: str, computer_id: str) -> bool:
        """Delete a computer by its Watchman ID (client_id) - NOT SUPPORTED BY API"""
        # Note: Computer deletion is not supported via the Watchman API
        # This method is kept for reference but will not work
        print("❌ Computer deletion is not supported by the Watchman API")
        return False

class DuplicateReporter:
    def __init__(self, api: WatchmanAPI):
        self.api = api
        
    def parse_last_report(self, last_report: str) -> Optional[datetime]:
        """Parse last_report timestamp into datetime object"""
        if not last_report:
            return None
            
        try:
            # Handle different possible formats
            if isinstance(last_report, int):
                return datetime.fromtimestamp(last_report)
            elif isinstance(last_report, str):
                # Try parsing ISO format first
                if 'T' in last_report:
                    # Remove timezone info for parsing
                    clean_date = last_report.split('.')[0].replace('T', ' ')
                    if '+' in clean_date or '-' in clean_date[-6:]:
                        clean_date = clean_date.split('+')[0].split('-')[0]
                    return datetime.strptime(clean_date, '%Y-%m-%d %H:%M:%S')
                else:
                    # Try parsing as timestamp
                    return datetime.fromtimestamp(float(last_report))
        except (ValueError, TypeError) as e:
            print(f"Warning: Could not parse last_report '{last_report}': {e}")
            return None
    
    def find_duplicates(self, computers: List[Dict]) -> Dict[str, List[Dict]]:
        """Find duplicate computers based on system_mac_address"""
        mac_groups = defaultdict(list)
        
        for computer in computers:
            system_mac = computer.get('system_mac_address')
            
            # Skip computers without system MAC address
            if not system_mac or system_mac.strip() == '':
                continue
                
            # Normalize MAC address (remove colons, hyphens, make lowercase)
            normalized_mac = system_mac.replace(':', '').replace('-', '').lower().strip()
            
            # Skip invalid MAC addresses
            if len(normalized_mac) != 12:
                continue
                
            mac_groups[normalized_mac].append(computer)
        
        # Filter to only groups with duplicates
        duplicates = {mac: computers for mac, computers in mac_groups.items() if len(computers) > 1}
        
        return duplicates
    
    def identify_devices_to_remove(self, duplicate_groups: Dict[str, List[Dict]]) -> List[Tuple[Dict, str]]:
        """Identify which devices should be removed (oldest last_report dates)"""
        devices_to_remove = []
        
        for mac_address, computers in duplicate_groups.items():
            print(f"\n--- Analyzing duplicates for MAC: {mac_address} ---")
            
            # Parse and sort by last_report date
            computer_dates = []
            for computer in computers:
                last_report_date = self.parse_last_report(computer.get('last_report'))
                computer_dates.append((computer, last_report_date))
                
                print(f"  {computer.get('computer_name', 'Unknown')} ({computer.get('client_id', 'Unknown ID')}) - "
                      f"Last Report: {last_report_date if last_report_date else 'Unknown'}")
            
            # Sort by date (newest first, None dates last)
            computer_dates.sort(key=lambda x: x[1] if x[1] is not None else datetime.min, reverse=True)
            
            # Keep the first (newest) computer, mark others for removal
            if len(computer_dates) > 1:
                keeper = computer_dates[0]
                to_remove = computer_dates[1:]
                
                print(f"  → KEEPING: {keeper[0].get('computer_name', 'Unknown')} ({keeper[0].get('client_id', 'Unknown ID')})")
                
                for computer, date in to_remove:
                    reason = f"Duplicate MAC {mac_address}, older report date"
                    devices_to_remove.append((computer, reason))
                    print(f"  → REMOVING: {computer.get('computer_name', 'Unknown')} ({computer.get('client_id', 'Unknown ID')}) - {reason}")
        
        return devices_to_remove
    
    def generate_report(self, devices_to_remove: List[Tuple[Dict, str]], duplicate_groups: Dict[str, List[Dict]]) -> Dict:
        """Generate a comprehensive duplicate devices report"""
        results = {
            'total_computers_analyzed': 0,
            'total_duplicate_groups': len(duplicate_groups),
            'total_duplicate_devices': sum(len(computers) for computers in duplicate_groups.values()),
            'devices_to_keep': [],
            'devices_to_remove': [],
            'duplicate_groups_detail': []
        }
        
        if not devices_to_remove and not duplicate_groups:
            print("✅ No duplicate devices found.")
            return results
        
        print(f"\n📊 DUPLICATE DEVICES REPORT")
        print("=" * 60)
        print(f"Found {len(duplicate_groups)} groups with duplicate MAC addresses")
        print(f"Total duplicate devices: {results['total_duplicate_devices']}")
        print(f"Devices that should be removed: {len(devices_to_remove)}")
        print()
        
        # Process each duplicate group
        for mac_address, computers in duplicate_groups.items():
            print(f"🔍 MAC Address: {mac_address}")
            print("-" * 40)
            
            # Parse and sort by last_report date
            computer_dates = []
            for computer in computers:
                last_report_date = self.parse_last_report(computer.get('last_report'))
                computer_dates.append((computer, last_report_date))
            
            # Sort by date (newest first, None dates last)
            computer_dates.sort(key=lambda x: x[1] if x[1] is not None else datetime.min, reverse=True)
            
            group_detail = {
                'mac_address': mac_address,
                'total_devices': len(computers),
                'device_to_keep': None,
                'devices_to_remove': []
            }
            
            # Process each device in the group
            for i, (computer, date) in enumerate(computer_dates):
                device_info = {
                    'computer_name': computer.get('computer_name', 'Unknown'),
                    'client_id': computer.get('client_id', 'Unknown'),
                    'uid': computer.get('uid', 'Unknown'),
                    'last_report': computer.get('last_report'),
                    'last_report_parsed': date.isoformat() if date else 'Unknown',
                    'group': computer.get('group', 'Unknown'),
                    'serial_number': computer.get('serial_number', 'Unknown'),
                    'os_version': computer.get('os_version', 'Unknown'),
                    'computer_url': computer.get('computer_url', 'N/A')
                }
                
                if i == 0:  # Keep the first (newest)
                    print(f"   ✅ KEEP: {device_info['computer_name']} ({device_info['client_id']})")
                    print(f"      Last Report: {device_info['last_report_parsed']}")
                    print(f"      Serial: {device_info['serial_number']}")
                    print(f"      OS: {device_info['os_version']}")
                    print(f"      URL: {device_info['computer_url']}")
                    
                    group_detail['device_to_keep'] = device_info
                    results['devices_to_keep'].append(device_info)
                else:  # Mark others for removal
                    print(f"   ❌ REMOVE: {device_info['computer_name']} ({device_info['client_id']})")
                    print(f"      Last Report: {device_info['last_report_parsed']}")
                    print(f"      Serial: {device_info['serial_number']}")
                    print(f"      OS: {device_info['os_version']}")
                    print(f"      URL: {device_info['computer_url']}")
                    print(f"      Reason: Older report date than keeper")
                    
                    group_detail['devices_to_remove'].append(device_info)
                    results['devices_to_remove'].append(device_info)
                
                print()
            
            results['duplicate_groups_detail'].append(group_detail)
            print()
        
        return results
    
    def export_report_to_csv(self, results: Dict, filename: str = 'watchman_duplicates_report.csv'):
        """Export the duplicate report to a CSV file"""
        try:
            import csv
            
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = [
                    'Status', 'MAC_Address', 'Computer_Name', 'Client_ID', 'UID',
                    'Last_Report', 'Serial_Number', 'OS_Version', 'Group',
                    'Computer_URL', 'Reason'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                # Write devices to keep
                for device in results['devices_to_keep']:
                    writer.writerow({
                        'Status': 'KEEP',
                        'MAC_Address': 'See group detail',
                        'Computer_Name': device['computer_name'],
                        'Client_ID': device['client_id'],
                        'UID': device['uid'],
                        'Last_Report': device['last_report_parsed'],
                        'Serial_Number': device['serial_number'],
                        'OS_Version': device['os_version'],
                        'Group': device['group'],
                        'Computer_URL': device['computer_url'],
                        'Reason': 'Most recent report date'
                    })
                
                # Write devices to remove
                for device in results['devices_to_remove']:
                    writer.writerow({
                        'Status': 'REMOVE',
                        'MAC_Address': 'See group detail',
                        'Computer_Name': device['computer_name'],
                        'Client_ID': device['client_id'],
                        'UID': device['uid'],
                        'Last_Report': device['last_report_parsed'],
                        'Serial_Number': device['serial_number'],
                        'OS_Version': device['os_version'],
                        'Group': device['group'],
                        'Computer_URL': device['computer_url'],
                        'Reason': 'Older report date than keeper'
                    })
            
            print(f"📄 Report exported to: {filename}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to export CSV: {e}")
            return False

    def remove_duplicates(self, devices_to_remove: List[Tuple[Dict, str]], dry_run: bool = True) -> Dict:
        """Generate report instead of removing duplicates (API doesn't support deletion)"""
        results = {
            'total_to_remove': len(devices_to_remove),
            'successfully_removed': 0,
            'failed_to_remove': 0,
            'removed_devices': [],
            'failed_devices': []
        }
        
        print(f"\n📋 REMOVAL SUMMARY")
        print("=" * 40)
        print("❌ Note: The Watchman API does not support computer deletion.")
        print("💡 You'll need to manually remove duplicates through the web interface.")
        print()
        print(f"📊 Devices identified for removal: {len(devices_to_remove)}")
        
        if devices_to_remove:
            print("\n🔗 To remove duplicates manually:")
            print("1. Log into your Watchman dashboard")
            print("2. Navigate to each computer using the URLs provided in the report")
            print("3. Use the 'Remove Computer' option for devices marked as 'REMOVE'")
            print("4. Keep devices marked as 'KEEP' (most recent report dates)")
        
        return results

class EmailReporter:
    def __init__(self, config: Dict):
        self.config = config
        self.smtp_configured = bool(config.get('smtp_server'))
    
    def send_report_email(self, results: Dict, csv_filename: str = None) -> bool:
        """Send the duplicate report via email"""
        if not self.smtp_configured:
            print("❌ Email not configured. Skipping email send.")
            return False
        
        try:
            # Create email content
            subject = f"Watchman Duplicate Devices Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            # Create HTML email body
            html_body = self._create_html_report(results)
            
            # Create text email body
            text_body = self._create_text_report(results)
            
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.config['email_from']
            msg['To'] = self.config['email_to']
            
            # Add both text and HTML parts
            part1 = MIMEText(text_body, 'plain')
            part2 = MIMEText(html_body, 'html')
            
            msg.attach(part1)
            msg.attach(part2)
            
            # Attach CSV file if provided
            if csv_filename and os.path.exists(csv_filename):
                with open(csv_filename, "rb") as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
                
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {os.path.basename(csv_filename)}'
                )
                msg.attach(part)
            
            # Send email
            context = ssl.create_default_context()
            
            with smtplib.SMTP(self.config['smtp_server'], self.config['smtp_port']) as server:
                if self.config.get('smtp_use_tls', True):
                    server.starttls(context=context)
                
                server.login(self.config['smtp_username'], self.config['smtp_password'])
                server.send_message(msg)
            
            print(f"✅ Email sent successfully to {self.config['email_to']}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to send email: {e}")
            return False
    
    def _create_html_report(self, results: Dict) -> str:
        """Create HTML formatted email report"""
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background-color: #f8f9fa; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
                .summary {{ background-color: #e9ecef; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
                .group {{ margin-bottom: 30px; border: 1px solid #dee2e6; border-radius: 5px; padding: 15px; }}
                .group-header {{ background-color: #007bff; color: white; padding: 10px; margin: -15px -15px 15px -15px; border-radius: 4px 4px 0 0; }}
                .device {{ margin: 10px 0; padding: 10px; border-radius: 3px; }}
                .keep {{ background-color: #d4edda; border-left: 4px solid #28a745; }}
                .remove {{ background-color: #f8d7da; border-left: 4px solid #dc3545; }}
                .device-info {{ margin: 5px 0; }}
                .url {{ color: #007bff; text-decoration: none; }}
                .url:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🎯 Watchman Duplicate Devices Report</h1>
                <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p><strong>Subdomain:</strong> {self.config.get('subdomain', 'N/A')}</p>
            </div>
            
            <div class="summary">
                <h2>📊 Summary</h2>
                <ul>
                    <li><strong>Duplicate Groups Found:</strong> {results.get('total_duplicate_groups', 0)}</li>
                    <li><strong>Total Duplicate Devices:</strong> {results.get('total_duplicate_devices', 0)}</li>
                    <li><strong>Devices to Keep:</strong> {len(results.get('devices_to_keep', []))}</li>
                    <li><strong>Devices to Remove:</strong> {len(results.get('devices_to_remove', []))}</li>
                </ul>
            </div>
        """
        
        if results.get('duplicate_groups_detail'):
            html += "<h2>📋 Detailed Groups</h2>"
            
            for group in results['duplicate_groups_detail']:
                html += f"""
                <div class="group">
                    <div class="group-header">
                        <strong>MAC Address:</strong> {group['mac_address']} 
                        ({group['total_devices']} devices)
                    </div>
                """
                
                # Device to keep
                if group.get('device_to_keep'):
                    device = group['device_to_keep']
                    html += f"""
                    <div class="device keep">
                        <strong>✅ KEEP:</strong> {device['computer_name']} ({device['client_id']})
                        <div class="device-info"><strong>Last Report:</strong> {device['last_report_parsed']}</div>
                        <div class="device-info"><strong>Serial:</strong> {device['serial_number']}</div>
                        <div class="device-info"><strong>OS:</strong> {device['os_version']}</div>
                        <div class="device-info"><a href="{device['computer_url']}" class="url">View in Watchman →</a></div>
                    </div>
                    """
                
                # Devices to remove
                for device in group.get('devices_to_remove', []):
                    html += f"""
                    <div class="device remove">
                        <strong>❌ REMOVE:</strong> {device['computer_name']} ({device['client_id']})
                        <div class="device-info"><strong>Last Report:</strong> {device['last_report_parsed']}</div>
                        <div class="device-info"><strong>Serial:</strong> {device['serial_number']}</div>
                        <div class="device-info"><strong>OS:</strong> {device['os_version']}</div>
                        <div class="device-info"><a href="{device['computer_url']}" class="url">Remove in Watchman →</a></div>
                    </div>
                    """
                
                html += "</div>"
        
        html += """
            <div class="summary">
                <h3>💡 Next Steps</h3>
                <ol>
                    <li>Review the devices marked as <strong style="color: #dc3545;">REMOVE</strong> above</li>
                    <li>Click the "Remove in Watchman" links to navigate to each device</li>
                    <li>Use Watchman's web interface to manually remove the older duplicates</li>
                    <li>Keep devices marked as <strong style="color: #28a745;">KEEP</strong> (most recent activity)</li>
                </ol>
                <p><em>Note: The Watchman API does not support automatic device removal, so manual removal through the web interface is required.</em></p>
            </div>
        </body>
        </html>
        """
        
        return html
    
    def _create_text_report(self, results: Dict) -> str:
        """Create plain text email report"""
        text = f"""
WATCHMAN DUPLICATE DEVICES REPORT
================================

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Subdomain: {self.config.get('subdomain', 'N/A')}

SUMMARY
-------
Duplicate Groups Found: {results.get('total_duplicate_groups', 0)}
Total Duplicate Devices: {results.get('total_duplicate_devices', 0)}
Devices to Keep: {len(results.get('devices_to_keep', []))}
Devices to Remove: {len(results.get('devices_to_remove', []))}

"""
        
        if results.get('duplicate_groups_detail'):
            text += "DETAILED GROUPS\n"
            text += "---------------\n\n"
            
            for group in results['duplicate_groups_detail']:
                text += f"MAC Address: {group['mac_address']} ({group['total_devices']} devices)\n"
                text += "-" * 50 + "\n"
                
                # Device to keep
                if group.get('device_to_keep'):
                    device = group['device_to_keep']
                    text += f"✅ KEEP: {device['computer_name']} ({device['client_id']})\n"
                    text += f"   Last Report: {device['last_report_parsed']}\n"
                    text += f"   Serial: {device['serial_number']}\n"
                    text += f"   OS: {device['os_version']}\n"
                    text += f"   URL: {device['computer_url']}\n\n"
                
                # Devices to remove
                for device in group.get('devices_to_remove', []):
                    text += f"❌ REMOVE: {device['computer_name']} ({device['client_id']})\n"
                    text += f"   Last Report: {device['last_report_parsed']}\n"
                    text += f"   Serial: {device['serial_number']}\n"
                    text += f"   OS: {device['os_version']}\n"
                    text += f"   URL: {device['computer_url']}\n"
                    text += f"   Reason: Older report date than keeper\n\n"
                
                text += "\n"
        
        text += """
NEXT STEPS
----------
1. Review the devices marked as 'REMOVE' above
2. Click the URLs to navigate to each device in Watchman
3. Use Watchman's web interface to manually remove the older duplicates
4. Keep devices marked as 'KEEP' (most recent activity)

Note: The Watchman API does not support automatic device removal, 
so manual removal through the web interface is required.
"""
        
        return text

def load_or_create_env():
    """
    Load environment variables from .env file or create one if it doesn't exist
    
    Returns:
        dict: Dictionary containing all configuration values
    """
    env_file = '.env'
    
    # Try to read existing .env file
    if os.path.exists(env_file):
        print("📄 Found .env file, loading configuration...")
        config = {}
        
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('WATCHMAN_SUBDOMAIN='):
                        config['subdomain'] = line.split('=', 1)[1].strip()
                    elif line.startswith('WATCHMAN_API_KEY='):
                        config['api_key'] = line.split('=', 1)[1].strip()
                    elif line.startswith('SMTP_SERVER='):
                        config['smtp_server'] = line.split('=', 1)[1].strip()
                    elif line.startswith('SMTP_PORT='):
                        config['smtp_port'] = int(line.split('=', 1)[1].strip())
                    elif line.startswith('SMTP_USERNAME='):
                        config['smtp_username'] = line.split('=', 1)[1].strip()
                    elif line.startswith('SMTP_PASSWORD='):
                        config['smtp_password'] = line.split('=', 1)[1].strip()
                    elif line.startswith('EMAIL_FROM='):
                        config['email_from'] = line.split('=', 1)[1].strip()
                    elif line.startswith('EMAIL_TO='):
                        config['email_to'] = line.split('=', 1)[1].strip()
                    elif line.startswith('SMTP_USE_TLS='):
                        config['smtp_use_tls'] = line.split('=', 1)[1].strip().lower() in ['true', '1', 'yes']
            
            # Check required Watchman fields
            if config.get('subdomain') and config.get('api_key'):
                print("✅ Watchman credentials loaded successfully!")
                if config.get('smtp_server'):
                    print("✅ Email configuration found!")
                else:
                    print("ℹ️  No email configuration found (optional)")
                return config
            else:
                print("⚠️  .env file exists but missing required Watchman variables.")
                
        except Exception as e:
            print(f"❌ Error reading .env file: {e}")
    
    # Create new .env file
    print("\n🔧 .env file not found or incomplete. Let's create one!")
    print("You'll need your Watchman Monitoring credentials:\n")
    
    print("=== WATCHMAN CONFIGURATION (Required) ===")
    print("1. Subdomain: This is the part before '.monitoringclient.com' in your URL")
    print("   Example: If your URL is 'https://mycompany.monitoringclient.com'")
    print("   Then your subdomain is: mycompany")
    subdomain = input("\nEnter your subdomain: ").strip()
    
    print("\n2. API Key: Get this from your Watchman dashboard")
    print("   Go to: Settings > API in your Watchman dashboard")
    print("   Generate or copy your API key")
    api_key = input("\nEnter your API key: ").strip()
    
    if not subdomain or not api_key:
        raise ValueError("Both subdomain and API key are required!")
    
    config = {
        'subdomain': subdomain,
        'api_key': api_key
    }
    
    # Optional email configuration
    print("\n=== EMAIL CONFIGURATION (Optional) ===")
    print("Configure email settings to send reports automatically.")
    setup_email = input("Do you want to configure email sending? (y/n): ").strip().lower()
    
    if setup_email in ['y', 'yes']:
        print("\nEmail Configuration:")
        print("Common SMTP settings:")
        print("  Gmail: smtp.gmail.com, port 587, TLS enabled")
        print("  Outlook: smtp-mail.outlook.com, port 587, TLS enabled")
        print("  Yahoo: smtp.mail.yahoo.com, port 587, TLS enabled")
        print("  Office 365: smtp.office365.com, port 587, TLS enabled")
        
        smtp_server = input("\nSMTP Server (e.g., smtp.gmail.com): ").strip()
        smtp_port = input("SMTP Port (usually 587 or 465): ").strip()
        smtp_username = input("SMTP Username (usually your email): ").strip()
        smtp_password = input("SMTP Password (or App Password): ").strip()
        email_from = input("From Email Address: ").strip()
        email_to = input("To Email Address (can be same as from): ").strip()
        use_tls = input("Use TLS encryption? (y/n): ").strip().lower()
        
        if smtp_server and smtp_port and smtp_username and smtp_password:
            config.update({
                'smtp_server': smtp_server,
                'smtp_port': int(smtp_port),
                'smtp_username': smtp_username,
                'smtp_password': smtp_password,
                'email_from': email_from or smtp_username,
                'email_to': email_to or smtp_username,
                'smtp_use_tls': use_tls in ['y', 'yes']
            })
            print("✅ Email configuration added!")
        else:
            print("ℹ️  Skipping email configuration (incomplete)")
    
    # Save to .env file
    try:
        with open(env_file, 'w') as f:
            f.write(f"# Watchman Monitoring Configuration\n")
            f.write(f"# Created automatically by duplicate report script\n\n")
            f.write(f"# Watchman API Settings (Required)\n")
            f.write(f"WATCHMAN_SUBDOMAIN={config['subdomain']}\n")
            f.write(f"WATCHMAN_API_KEY={config['api_key']}\n\n")
            
            if config.get('smtp_server'):
                f.write(f"# Email Settings (Optional)\n")
                f.write(f"SMTP_SERVER={config['smtp_server']}\n")
                f.write(f"SMTP_PORT={config['smtp_port']}\n")
                f.write(f"SMTP_USERNAME={config['smtp_username']}\n")
                f.write(f"SMTP_PASSWORD={config['smtp_password']}\n")
                f.write(f"EMAIL_FROM={config['email_from']}\n")
                f.write(f"EMAIL_TO={config['email_to']}\n")
                f.write(f"SMTP_USE_TLS={str(config['smtp_use_tls']).lower()}\n")
        
        print(f"\n✅ .env file created successfully!")
        print(f"📁 Location: {os.path.abspath(env_file)}")
        print("🔒 Keep this file secure - it contains your API credentials!")
        
        return config
        
    except Exception as e:
        raise ValueError(f"Failed to create .env file: {e}")

def print_summary(results: Dict):
    """Print summary of the duplicate analysis"""
    print(f"\n📈 FINAL SUMMARY")
    print("=" * 40)
    print(f"Total duplicate groups found: {results.get('total_duplicate_groups', 0)}")
    print(f"Total duplicate devices: {results.get('total_duplicate_devices', 0)}")
    print(f"Devices to keep (newest): {len(results.get('devices_to_keep', []))}")
    print(f"Devices to remove (older): {len(results.get('devices_to_remove', []))}")
    
    if results.get('devices_to_remove'):
        print(f"\n💡 Next Steps:")
        print(f"1. Review the detailed report above")
        print(f"2. Manually remove devices marked as 'REMOVE' through Watchman web interface")
        print(f"3. Keep devices marked as 'KEEP' (they have the most recent report dates)")
        print(f"4. Use the computer URLs provided to navigate directly to each device")

def main():
    parser = argparse.ArgumentParser(description='Generate report of duplicate devices in Watchman Monitoring')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('--subdomain', help='Override subdomain from .env file')
    parser.add_argument('--api-key', help='Override API key from .env file')
    parser.add_argument('--reset-env', action='store_true', help='Reset .env file with new credentials')
    parser.add_argument('--export-csv', action='store_true', help='Export report to CSV file')
    parser.add_argument('--csv-filename', default='watchman_duplicates_report.csv', help='CSV filename (default: watchman_duplicates_report.csv)')
    parser.add_argument('--no-email', action='store_true', help='Disable automatic email sending')
    parser.add_argument('--email-only', action='store_true', help='Send email only, suppress console output')
    
    args = parser.parse_args()
    
    try:
        # Handle --reset-env flag
        if args.reset_env:
            if os.path.exists('.env'):
                print("🗑️  Removing existing .env file...")
                os.remove('.env')
            print("🔧 Creating new .env file...")
        
        # Load configuration from .env or command line
        if args.subdomain and args.api_key:
            config = {
                'subdomain': args.subdomain,
                'api_key': args.api_key
            }
            if not args.email_only:
                print("Using credentials from command line arguments")
        else:
            if not args.email_only:
                print("Loading configuration from .env file...")
            config = load_or_create_env()
            if not args.email_only:
                print(f"✅ Loaded configuration for subdomain: {config['subdomain']}")
        
        # Initialize API client and email reporter
        api = WatchmanAPI(config['subdomain'], config['api_key'])
        reporter = DuplicateReporter(api)
        email_reporter = EmailReporter(config)
        
        # Determine if email should be sent
        send_email = not args.no_email and email_reporter.smtp_configured
        
        if not args.email_only:
            print("🎯 Watchman Duplicate Device Report")
            print("=" * 50)
            if send_email:
                print(f"📧 Email will be sent to: {config.get('email_to', 'configured recipient')}")
            elif not email_reporter.smtp_configured:
                print("ℹ️  Email not configured - report will only be displayed")
            else:
                print("ℹ️  Email disabled with --no-email flag")
        
        # Fetch all computers
        computers = api.get_all_computers()
        
        if not computers:
            if not args.email_only:
                print("No computers found in Watchman.")
            sys.exit(0)
        
        # Find duplicates
        if not args.email_only:
            print(f"\n📊 Analyzing {len(computers)} computers for duplicates...")
        duplicate_groups = reporter.find_duplicates(computers)
        
        if not duplicate_groups:
            message = "✅ No duplicate devices found based on System MAC Address."
            if not args.email_only:
                print(message)
            
            # DO NOT send email if no duplicates found
            if not args.email_only and send_email:
                print("ℹ️  No email sent - no duplicates to report")
            
            sys.exit(0)
        
        # Only proceed with email/reporting if duplicates are found
        if not args.email_only:
            print(f"⚠️  Found duplicates! Preparing detailed report...")
        
        # Identify devices to remove
        devices_to_remove = reporter.identify_devices_to_remove(duplicate_groups)
        
        # Generate comprehensive report
        if args.email_only:
            # Minimal output for email-only mode
            results = {
                'total_duplicate_groups': len(duplicate_groups),
                'total_duplicate_devices': sum(len(computers) for computers in duplicate_groups.values()),
                'devices_to_keep': [],
                'devices_to_remove': [],
                'duplicate_groups_detail': []
            }
            
            # Process groups for email
            for mac_address, computers in duplicate_groups.items():
                computer_dates = []
                for computer in computers:
                    last_report_date = reporter.parse_last_report(computer.get('last_report'))
                    computer_dates.append((computer, last_report_date))
                
                computer_dates.sort(key=lambda x: x[1] if x[1] is not None else datetime.min, reverse=True)
                
                group_detail = {
                    'mac_address': mac_address,
                    'total_devices': len(computers),
                    'device_to_keep': None,
                    'devices_to_remove': []
                }
                
                for i, (computer, date) in enumerate(computer_dates):
                    device_info = {
                        'computer_name': computer.get('computer_name', 'Unknown'),
                        'client_id': computer.get('client_id', 'Unknown'),
                        'uid': computer.get('uid', 'Unknown'),
                        'last_report': computer.get('last_report'),
                        'last_report_parsed': date.isoformat() if date else 'Unknown',
                        'group': computer.get('group', 'Unknown'),
                        'serial_number': computer.get('serial_number', 'Unknown'),
                        'os_version': computer.get('os_version', 'Unknown'),
                        'computer_url': computer.get('computer_url', 'N/A')
                    }
                    
                    if i == 0:
                        group_detail['device_to_keep'] = device_info
                        results['devices_to_keep'].append(device_info)
                    else:
                        group_detail['devices_to_remove'].append(device_info)
                        results['devices_to_remove'].append(device_info)
                
                results['duplicate_groups_detail'].append(group_detail)
        else:
            results = reporter.generate_report(devices_to_remove, duplicate_groups)
        
        # Export to CSV if requested
        csv_file = None
        if args.export_csv:
            if reporter.export_report_to_csv(results, args.csv_filename):
                csv_file = args.csv_filename
        
        # Send email automatically if configured and duplicates found
        if send_email:
            if not args.email_only:
                print(f"\n📧 Sending email report...")
            email_sent = email_reporter.send_report_email(results, csv_file)
            
            if not args.email_only:
                if email_sent:
                    print(f"✅ Email report sent successfully!")
                else:
                    print(f"❌ Failed to send email report")
        
        # Print summary (unless email-only mode)
        if not args.email_only:
            print_summary(results)
        
    except KeyboardInterrupt:
        if not args.email_only:
            print("\n❌ Operation cancelled by user.")
        sys.exit(1)
    except ValueError as e:
        if not args.email_only:
            print(f"❌ Configuration Error: {e}")
        sys.exit(1)
    except Exception as e:
        if not args.email_only:
            print(f"❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()