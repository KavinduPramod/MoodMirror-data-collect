# Reddit Data Collector - DigitalOcean Deployment Guide

## Prerequisites
- DigitalOcean droplet (2GB RAM, 2 vCPU)
- SSH access to your droplet
- Your project files ready

---

## Step-by-Step Deployment

### 1. Initial Server Setup

```bash
# SSH into your droplet
ssh root@YOUR_DROPLET_IP

# Update system
apt update && apt upgrade -y

# Create user for the project
useradd -m -s /bin/bash fyp
passwd fyp  # Set a password

# Add user to sudo group (optional, for admin tasks)
usermod -aG sudo fyp

# Switch to fyp user
su - fyp
```

---

### 2. Create Project Directory Structure

```bash
# Create main project directory
mkdir -p /home/fyp/data-collection

# Create logs directory
mkdir -p /home/fyp/data-collection/logs

# Create data directory
mkdir -p /home/fyp/data-collection/data

# Set proper permissions
chmod 755 /home/fyp/data-collection
chmod 755 /home/fyp/data-collection/logs
chmod 755 /home/fyp/data-collection/data
```

---

### 3. Install Python Dependencies

```bash
# Install Python and pip (as root or with sudo)
exit  # Exit fyp user back to root
apt install python3 python3-pip python3-venv git -y

# Switch back to fyp user
su - fyp

# Create virtual environment (OPTIONAL but recommended)
cd /home/fyp/data-collection
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install required packages
pip3 install praw vaderSentiment numpy

# OR if using requirements.txt:
# pip3 install -r requirement.txt
```

---

### 4. Upload Project Files

**Option A: From your local machine (Windows PowerShell)**

```powershell
# Navigate to your project folder
cd C:\Users\kavin\Desktop\FYP\reddit-scrape

# Upload essential files (replace YOUR_DROPLET_IP)
scp -i ~/.ssh/id_kavindu collect.py fyp@YOUR_DROPLET_IP:/home/fyp/data-collection/
scp -i ~/.ssh/id_kavindu config.json fyp@YOUR_DROPLET_IP:/home/fyp/data-collection/
scp -i ~/.ssh/id_kavindu credentials.json fyp@YOUR_DROPLET_IP:/home/fyp/data-collection/
scp -i ~/.ssh/id_kavindu requirement.txt fyp@YOUR_DROPLET_IP:/home/fyp/data-collection/
```

**Option B: Using Git (if pushed to GitHub)**

```bash
# On the droplet as fyp user
cd /home/fyp/data-collection
git clone https://github.com/KavinduPramod/MoodMirror-data-collect.git .

# Add your credentials.json manually (don't commit this to git!)
nano credentials.json
# Paste your credentials and save (Ctrl+O, Enter, Ctrl+X)
```

---

### 5. Update Configuration for Production

```bash
# Edit config.json to ensure it targets 3000 users
nano /home/fyp/data-collection/config.json
```

Make sure these values are set:
```json
{
  "collection_settings": {
    "target_users": 3000,
    "time_window_days": 75,
    "posts_to_scan_per_subreddit": 120
  }
}
```

---

### 6. Install and Configure the Systemd Service

```bash
# Exit fyp user back to root
exit

# Copy service file to systemd directory
cp /home/fyp/data-collection/reddit-collector.service /etc/systemd/system/

# OR create it manually:
nano /etc/systemd/system/reddit-collector.service
# Paste the service file content and save

# If using virtual environment, update the service file ExecStart line:
nano /etc/systemd/system/reddit-collector.service
# Change: ExecStart=/usr/bin/python3 /home/fyp/data-collection/collect.py
# To:     ExecStart=/home/fyp/data-collection/venv/bin/python3 /home/fyp/data-collection/collect.py

# Reload systemd to recognize new service
systemctl daemon-reload

# Enable service to start on boot
systemctl enable reddit-collector.service
```

---

### 7. Start the Collection Service

```bash
# Start the service
systemctl start reddit-collector.service

# Check status
systemctl status reddit-collector.service

# Should show: "active (running)"
```

---

### 8. Monitor the Collection Process

#### **Real-time Log Monitoring**

```bash
# Watch main collector log (live updates)
tail -f /home/fyp/data-collection/logs/collector.log

# Watch error log
tail -f /home/fyp/data-collection/logs/collector-error.log

# View last 100 lines
tail -n 100 /home/fyp/data-collection/logs/collector.log

# Search for specific info
grep "COLLECTED" /home/fyp/data-collection/logs/collector.log
grep "ERROR" /home/fyp/data-collection/logs/collector-error.log
```

#### **Service Status Commands**

```bash
# Check if service is running
systemctl status reddit-collector.service

# View service logs (from systemd journal)
journalctl -u reddit-collector.service -f

# View last 50 lines
journalctl -u reddit-collector.service -n 50

# View logs since boot
journalctl -u reddit-collector.service -b
```

#### **Check Progress in JSON File**

```bash
# Count collected users
python3 -c "import json; data=json.load(open('/home/fyp/data-collection/data/collected_users.json')); print(f'Users collected: {len(data)}')"

# OR using jq (install with: apt install jq)
jq 'length' /home/fyp/data-collection/data/collected_users.json
```

#### **Resource Monitoring**

```bash
# Watch memory and CPU usage
htop

# OR simple monitoring
watch -n 5 'free -h && ps aux | grep collect.py'

# Check disk usage
df -h /home/fyp/data-collection
```

---

### 9. Service Management Commands

```bash
# Stop the service
systemctl stop reddit-collector.service

# Restart the service
systemctl restart reddit-collector.service

# Disable auto-start on boot
systemctl disable reddit-collector.service

# Re-enable auto-start
systemctl enable reddit-collector.service

# View full service configuration
systemctl cat reddit-collector.service
```

---

### 10. Download Collected Data (When Complete)

**From your local machine (Windows PowerShell):**

```powershell
# Download the collected data
scp -i ~/.ssh/id_kavindu fyp@YOUR_DROPLET_IP:/home/fyp/data-collection/data/collected_users.json C:\Users\kavin\Desktop\

# Download logs
scp -i ~/.ssh/id_kavindu fyp@YOUR_DROPLET_IP:/home/fyp/data-collection/logs/collector.log C:\Users\kavin\Desktop\

# Download population baseline
scp -i ~/.ssh/id_kavindu fyp@YOUR_DROPLET_IP:/home/fyp/data-collection/data/population_baseline.json C:\Users\kavin\Desktop\
```

---

## Service File Explained

### Resource Optimization Settings:

```ini
Nice=-5                    # Higher priority than default processes
IOSchedulingClass=best-effort  # Balanced I/O scheduling
IOSchedulingPriority=2     # Higher I/O priority
CPUWeight=200              # Get 2x CPU time compared to default (100)
MemoryHigh=1.5G            # Soft memory limit (throttle if exceeded)
MemoryMax=1.8G             # Hard memory limit (kill if exceeded)
```

### Why These Settings?

- **Nice=-5**: Gives your collector priority over background tasks
- **CPUWeight=200**: Ensures it gets CPU when needed (still shares fairly)
- **MemoryHigh/Max**: Protects system from OOM while allowing full use of available RAM
- **IOSchedulingClass**: Optimizes disk writes for JSON saves
- **Restart=on-failure**: Auto-restarts if it crashes (max 3 times in 5 mins)

---

## Troubleshooting

### Service won't start
```bash
# Check detailed error
journalctl -u reddit-collector.service -n 50

# Check file permissions
ls -la /home/fyp/data-collection/

# Check Python path
which python3

# Test manually
su - fyp
cd /home/fyp/data-collection
python3 collect.py
```

### Out of memory
```bash
# Check memory usage
free -h

# Increase MemoryMax in service file
nano /etc/systemd/system/reddit-collector.service
# Change MemoryMax=1.8G to MemoryMax=1.9G

# Reload and restart
systemctl daemon-reload
systemctl restart reddit-collector.service
```

### Logs not appearing
```bash
# Check logs directory exists and is writable
ls -la /home/fyp/data-collection/logs/
chmod 755 /home/fyp/data-collection/logs/

# Check service file paths
systemctl cat reddit-collector.service
```

---

## Expected Timeline

- **Total time**: 30-40 hours (1.5-2 days)
- **Users per hour**: ~75-100 users
- **Check progress**: Every 6-12 hours
- **Dataset size**: ~500MB-1GB when complete

---

## Security Notes

1. **Never commit credentials.json to Git**
2. **Set proper file permissions**: `chmod 600 credentials.json`
3. **Consider firewall**: Only allow SSH (port 22)
4. **Use SSH keys**: Disable password authentication
5. **Keep system updated**: `apt update && apt upgrade` regularly

---

## Quick Reference

```bash
# Start collection
systemctl start reddit-collector.service

# Watch progress
tail -f /home/fyp/data-collection/logs/collector.log

# Check status
systemctl status reddit-collector.service

# Stop collection
systemctl stop reddit-collector.service
```

---

**Good luck with your data collection! 🚀**
