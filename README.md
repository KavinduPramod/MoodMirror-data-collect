# Reddit Mental Health Data Collector

## Overview
This project collects anonymized Reddit user data from a wide range of mental health-related subreddits. The goal is to gather enough high-quality data to train machine learning models for mental health research and analysis.

## Data Collected
- **User Posts & Comments**: For each user, the script collects their posts and comments from the last 60 days.
- **Features Extracted**:
  - Temporal features (posting frequency, time span, late-night activity)
  - Sentiment analysis (average sentiment, negative post ratio)
  - Linguistic features (first-person pronoun ratio)
  - Engagement (average score)
  - Community features (subreddit diversity, mental health subreddit participation)
- **Anonymization**:
  - No usernames are stored. Each user is assigned a unique anonymous ID and a hash.
  - All data is saved in `data/collected_users.json`.

## Subreddits Targeted
The script scans posts and comments from 22 mental health-related subreddits, including:
- depression, anxiety, mentalhealth, lonely, offmychest, CasualConversation, decidingtobebetter
- suicidewatch, bipolarreddit, BPD, ADHD, OCD, PTSD, addiction, EDAnonymous, socialanxiety, Agoraphobia, panicattack, getting_over_it, TrueOffMyChest, selfimprovement, mentalillness

## How Data Is Collected
1. **Configuration**: Settings are defined in `config.json` (number of users, time window, subreddits, etc.).
2. **Reddit API**: Uses PRAW (Python Reddit API Wrapper) and credentials from `credentials.json`.
3. **User Discovery**: Finds active users in each subreddit by scanning recent posts and comments.
4. **Data Collection**: For each candidate user, collects all posts and comments within the time window.
5. **Quality Filtering**: Only users meeting minimum activity and diversity criteria are included.
6. **Feature Extraction**: Computes features for each user for ML purposes.
7. **Anonymization**: Usernames are hashed and replaced with anonymous IDs.
8. **Saving**: Data is incrementally saved to `data/collected_users.json`.

## Usage
1. Place your Reddit API credentials in `credentials.json`.
2. Adjust settings in `config.json` as needed.
3. Run the script:
   ```powershell
   python collect.py
   ```
4. Collected data will be saved in `data/collected_users.json`.

## Requirements
- Python 3.x
- PRAW
- vaderSentiment

Install dependencies:
```powershell
pip install praw vaderSentiment
```

## Notes
- The script respects Reddit API rate limits and is designed for ethical data collection.
- All data is anonymized and suitable for research and machine learning.

---


