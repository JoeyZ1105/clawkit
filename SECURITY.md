# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 3.x     | :white_check_mark: |
| < 3.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in ClawKit, please report it responsibly:

1. **Do NOT** open a public GitHub issue for security vulnerabilities
2. Email the maintainer directly (check the repository owner's profile for contact info)
3. Include a detailed description of the vulnerability and steps to reproduce

### What to Include

- Type of vulnerability (e.g., code injection, data exposure)
- Full paths and affected files
- Steps to reproduce the issue
- Potential impact
- Suggested fix (if any)

### Response Timeline

- Initial response: within 48 hours
- Status update: within 7 days
- Fix timeline: depends on severity and complexity

## Security Considerations for Users

### Cookie Storage

ClawKit stores platform cookies in `~/.clawkit/cookies.json`. This file contains session credentials:

- Keep this file private (it's excluded from git by default)
- Do not share cookie files with others
- Periodically clear and refresh cookies

### Network Traffic

ClawKit makes HTTP requests to social media platforms:

- Requests may be logged by target platforms
- Use responsibly and within platform ToS
- Consider using a VPN if privacy is a concern

### Optional Dependencies

Some optional features require third-party packages:

- `google-genai`: Sends data to Google's API for OCR/analysis (requires API key)
- `playwright`: Runs browser automation (may download browser binaries)

Review the privacy policies of these services before enabling.
