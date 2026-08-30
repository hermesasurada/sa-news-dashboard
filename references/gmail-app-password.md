# Gmail App Password Storage

Store Gmail app passwords in this file for himalaya CLI.

Format: 16-character app password (4 groups of 4, space-separated)
Example: `xxxx xxxx xxxx xxxx`

## Setup
1. Google Account → Security → App Passwords
2. App: Mail, Device: Other → Generate
3. Copy password here
4. Reference in config: `backend.auth.cmd = "cat ~/.hermes/data/email_password.txt"`

## Security
- This file should NOT be committed to git
- Add to `.gitignore` if in a repo
- chmod 600 for extra security
