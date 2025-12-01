#!/usr/bin/env python3
"""
Simple Reddit Mental Health Data Collector
One script, easy to understand and run
"""

import praw
import json
import time
from datetime import datetime, timedelta
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import hashlib
import numpy as np
import requests

# ============================================================================
# CONFIGURATION LOADING
# ============================================================================

print("\n" + "="*70)
print("🧠 REDDIT MENTAL HEALTH DATA COLLECTOR")
print("="*70 + "\n")

# Load credentials
print("📋 Loading credentials...")
with open('credentials.json', 'r') as f:
    credentials = json.load(f)

# Load configuration
print("⚙️  Loading configuration...")
with open('config.json', 'r') as f:
    config = json.load(f)

settings = config['collection_settings']

print(f"   Target: {settings['target_users']} users")
print(f"   Minimum posts per user: {settings['min_posts_per_user']}")
print(f"   Time window: {settings['time_window_days']} days")
print(f"   Subreddits to search: {len(config['subreddits_to_search'])}")

# ============================================================================
# REDDIT CONNECTION
# ============================================================================

print("\n🔌 Connecting to Reddit API...")
reddit = praw.Reddit(
    client_id=credentials['client_id'],
    client_secret=credentials['client_secret'],
    user_agent=credentials['user_agent']
)

# Test connection
try:
    reddit.user.me()
    print("✅ Connected successfully (read-only mode)")
except:
    print("✅ Connected successfully")

# Initialize sentiment analyzer
sentiment_analyzer = SentimentIntensityAnalyzer()

# Extract mental health subreddits from config (used multiple times)
mental_health_subs = [sub.lower() for sub in config['subreddits_to_search']]

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_users_from_subreddit(subreddit_name, sort_method, limit):
    """
    Find active users in a subreddit
    Returns: set of anonymous user hashes
    """
    print(f"\n🔍 Searching r/{subreddit_name} ({sort_method})...")
    
    try:
        subreddit = reddit.subreddit(subreddit_name)
        users = set()
        
        # Get posts based on sort method
        if sort_method == 'hot':
            posts = subreddit.hot(limit=limit)
        elif sort_method == 'new':
            posts = subreddit.new(limit=limit)
        elif sort_method == 'top':
            posts = subreddit.top(time_filter='week', limit=limit)
        elif sort_method == 'rising':
            posts = subreddit.rising(limit=limit)
        elif sort_method == 'controversial':
            posts = subreddit.controversial(time_filter='week', limit=limit)
        else:
            posts = subreddit.hot(limit=limit)
        
        # Collect usernames
        post_count = 0
        for post in posts:
            post_count += 1
            
            # Add post author
            if post.author and post.author.name not in ['[deleted]', 'AutoModerator']:
                users.add(post.author.name)
            
            # Add commenters (first 10 comments only to be fast)
            try:
                post.comments.replace_more(limit=0)
                for comment in post.comments.list()[:10]:
                    if comment.author and comment.author.name not in ['[deleted]', 'AutoModerator']:
                        users.add(comment.author.name)
            except:
                pass
            
            # Small delay to respect rate limits
            time.sleep(0.1)
        
        print(f"   Scanned {post_count} posts, found {len(users)} unique users")
        return users
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return set()


def collect_user_posts(username, days_back):
    """
    Collect all posts from a user in the last N days
    Returns: list of posts (or empty list if error)
    Note: Username is only used for API access, never stored
    """
    try:
        user = reddit.redditor(username)
        posts = []
        
        cutoff_date = datetime.now() - timedelta(days=days_back)
        
        # Collect submissions (posts)
        for submission in user.submissions.new(limit=None):
            post_date = datetime.fromtimestamp(submission.created_utc)
            
            if post_date < cutoff_date:
                break
            
            text = submission.title + " " + (submission.selftext or "")
            
            posts.append({
                'type': 'post',
                'text': text,
                'timestamp': submission.created_utc,
                'date': post_date.strftime('%Y-%m-%d %H:%M:%S'),
                'subreddit': submission.subreddit.display_name,
                'score': submission.score,
                'num_comments': submission.num_comments
            })
            
            time.sleep(0.1)  # Rate limit
        
        # Collect comments
        for comment in user.comments.new(limit=None):
            comment_date = datetime.fromtimestamp(comment.created_utc)
            
            if comment_date < cutoff_date:
                break
            
            posts.append({
                'type': 'comment',
                'text': comment.body,
                'timestamp': comment.created_utc,
                'date': comment_date.strftime('%Y-%m-%d %H:%M:%S'),
                'subreddit': comment.subreddit.display_name,
                'score': comment.score,
                'num_comments': 0
            })
            
            time.sleep(0.1)  # Rate limit
        
        # EARLY FILTER: Quick MH participation check to save time
        early_filter_threshold = settings.get('early_mh_filter_threshold', 10)
        if len(posts) >= early_filter_threshold:
            mh_posts = sum(1 for p in posts if p['subreddit'].lower() in mental_health_subs)
            mh_ratio = mh_posts / len(posts)
            
            # If MH ratio is way too low, return empty to skip detailed analysis
            # Use 60% of required ratio for early filtering to be efficient
            early_filter_ratio = settings.get('min_mh_participation_ratio', 0.40) * 0.6
            if mh_ratio < early_filter_ratio:
                return []  # This user won't meet threshold, skip early
        
        # Sort by time
        posts.sort(key=lambda x: x['timestamp'])
        
        return posts
        
    except Exception as e:
        print(f"      Error collecting {username}: {e}")
        return []


def calculate_baseline_stability(posts):
    """
    Calculate stability coefficient by comparing odd vs even post baselines
    Returns: stability_coefficient (0-1)
    """
    if len(posts) < 20:
        return 0.0  # Insufficient data for stability check
    
    # Split posts into odd/even indices
    odd_posts = [p for i, p in enumerate(posts) if i % 2 == 1]
    even_posts = [p for i, p in enumerate(posts) if i % 2 == 0]
    
    # Calculate sentiment means for each half
    odd_sentiment = sum(sentiment_analyzer.polarity_scores(p['text'])['compound'] 
                       for p in odd_posts) / len(odd_posts)
    even_sentiment = sum(sentiment_analyzer.polarity_scores(p['text'])['compound'] 
                        for p in even_posts) / len(even_posts)
    
    # Calculate stability (1 - difference between halves)
    stability = 1 - abs(odd_sentiment - even_sentiment)
    
    return max(0, stability)


def calculate_z_scores(posts):
    """
    Calculate z-scores for behavioral metrics to establish personalized baselines
    Z = (current_score - user_mean) / user_std
    """
    # Extract time-series of metrics
    sentiments = [sentiment_analyzer.polarity_scores(p['text'])['compound'] for p in posts]
    
    if len(sentiments) < 2:
        return None
    
    # Calculate mean and std for user
    user_mean = np.mean(sentiments)
    user_std = np.std(sentiments)
    
    if user_std == 0:
        return None  # Cannot calculate z-scores with zero variance
    
    # Calculate z-scores for each post
    z_scores = [(s - user_mean) / user_std for s in sentiments]
    
    return {
        'user_mean_sentiment': float(user_mean),
        'user_std_sentiment': float(user_std),
        'max_z_score': float(max(abs(z) for z in z_scores)),
        'deviations_z_gt_2': sum(1 for z in z_scores if abs(z) > 2),
        'z_scores_timeline': [float(z) for z in z_scores]  # For temporal analysis
    }


def calculate_confidence_score(post_count, minimum_reliable_threshold=30):
    """
    Calculate confidence score based on post count
    Returns: confidence_score (0-1), 1.0 = sufficient data for full personalization
    """
    return min(1.0, post_count / minimum_reliable_threshold)


def calculate_temporal_consistency(posts):
    """
    Calculate posting consistency over time
    Returns: consistency_score (0-1)
    """
    timestamps = [p['timestamp'] for p in posts]
    
    if len(timestamps) < 2:
        return 0.0
    
    # Calculate inter-post intervals (in days)
    intervals = [(timestamps[i+1] - timestamps[i]) / 86400 
                 for i in range(len(timestamps)-1)]
    
    if not intervals:
        return 0.0
    
    # Calculate coefficient of variation (lower = more consistent)
    mean_interval = np.mean(intervals)
    std_interval = np.std(intervals)
    
    if mean_interval == 0:
        return 0.0
    
    cv = std_interval / mean_interval
    
    # Convert to 0-1 score (lower CV = higher consistency)
    consistency = max(0, 1 - (cv / 5))  # Normalize assuming CV rarely >5
    
    return float(consistency)


def check_user_quality(posts):
    """
    Check if user meets quality criteria
    Returns: (pass/fail, reason)
    """
    # Check 1: Minimum post count
    if len(posts) < settings['min_posts_per_user']:
        return False, f"Only {len(posts)} posts (need {settings['min_posts_per_user']})"
    
    # Check 2: Time span (not all posts in one day)
    timestamps = [p['timestamp'] for p in posts]
    time_span_days = (max(timestamps) - min(timestamps)) / 86400
    
    min_time_span = settings.get('min_time_span_days', 7)
    if time_span_days < min_time_span:
        return False, f"All posts within {time_span_days:.1f} days (need {min_time_span}+ days spread)"
    
    # Check 3: Average text length
    avg_length = sum(len(p['text']) for p in posts) / len(posts)
    
    if avg_length < settings['min_text_length']:
        return False, f"Posts too short (avg {avg_length:.0f} chars)"
    
    # Check 4: Subreddit diversity
    subreddits = set(p['subreddit'] for p in posts)
    
    if len(subreddits) < settings['min_subreddits']:
        return False, f"Only {len(subreddits)} different subreddits (need {settings['min_subreddits']})"
    
    # Check 5: Mental health participation (using config)
    mh_posts = sum(1 for p in posts if p['subreddit'].lower() in mental_health_subs)
    mh_ratio = mh_posts / len(posts)
    
    if 'min_mh_posts' in settings and mh_posts < settings['min_mh_posts']:
        return False, f"Only {mh_posts} mental health posts (need {settings['min_mh_posts']})"
    
    if 'min_mh_participation_ratio' in settings and mh_ratio < settings['min_mh_participation_ratio']:
        return False, f"Only {mh_ratio:.1%} MH participation (need {settings['min_mh_participation_ratio']:.1%})"
    
    # Check 6: Baseline stability (for users with enough posts)
    min_posts_for_stability = settings.get('min_posts_for_stability_check', 20)
    if len(posts) >= min_posts_for_stability and 'min_baseline_stability' in settings:
        baseline_stability = calculate_baseline_stability(posts)
        if baseline_stability < settings['min_baseline_stability']:
            return False, f"Low baseline stability ({baseline_stability:.2f}, need {settings['min_baseline_stability']:.2f})"
    
    return True, "Passed all checks"


def validate_sentiment_distribution(posts):
    """
    Validate that user's sentiment distribution is consistent with mental health populations
    Returns: (pass/fail, reason, avg_sentiment)
    """
    min_posts_for_sentiment = settings.get('min_posts_for_sentiment_check', 10)
    if len(posts) < min_posts_for_sentiment:
        return False, f"Insufficient posts for sentiment validation (need {min_posts_for_sentiment})", 0.0
    
    # Get validation thresholds from config (with fallback values)
    if 'sentiment_validation' in settings:
        min_sent = settings['sentiment_validation'].get('min_sentiment', -0.6)
        max_sent = settings['sentiment_validation'].get('max_sentiment', 0.25)
        min_neg_posts = settings['sentiment_validation'].get('require_negative_posts', 10)
    else:
        # Fallback if not in config
        min_sent = -0.6
        max_sent = 0.25
        min_neg_posts = 10
    
    # Calculate sentiment for all posts
    sentiments = [sentiment_analyzer.polarity_scores(p['text'])['compound'] 
                  for p in posts]
    
    avg_sentiment = np.mean(sentiments)
    negative_posts = sum(1 for s in sentiments if s < -0.05)
    
    # Check if sentiment is in expected range for MH populations
    if avg_sentiment > max_sent:
        return False, f"Average sentiment too positive ({avg_sentiment:.3f}, expected {min_sent} to {max_sent})", avg_sentiment
    
    if avg_sentiment < min_sent:
        return False, f"Average sentiment unusually negative ({avg_sentiment:.3f}, may indicate bot/spam)", avg_sentiment
    
    # Check minimum negative posts requirement
    if negative_posts < min_neg_posts:
        return False, f"Only {negative_posts} negative posts (expected {min_neg_posts}+)", avg_sentiment
    
    return True, "Sentiment distribution validated", avg_sentiment


def send_email_notification(milestone, total_users, avg_posts, avg_sentiment, time_elapsed):
    """
    Send email notification at collection milestones using Resend API
    """
    if 'resend_api_key' not in credentials or 'notification_email' not in credentials:
        print("   ⚠️  Email notification skipped - Resend API key or email not configured")
        return
    
    try:
        # Calculate progress
        progress_percent = (total_users / settings['target_users']) * 100
        hours = int(time_elapsed // 3600)
        minutes = int((time_elapsed % 3600) // 60)
        
        # HTML body
        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif;">
            <h2 style="color: #2ecc71;">✅ Milestone Reached: {milestone} Users!</h2>
            
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
              <h3 style="color: #34495e;">📊 Progress Update</h3>
              <ul style="font-size: 16px; line-height: 1.8;">
                <li><strong>Users Collected:</strong> {total_users} / {settings['target_users']} ({progress_percent:.1f}%)</li>
                <li><strong>Average Posts per User:</strong> {avg_posts:.1f}</li>
                <li><strong>Average Sentiment:</strong> {avg_sentiment:.3f}</li>
                <li><strong>Time Elapsed:</strong> {hours}h {minutes}m</li>
              </ul>
            </div>
            
            <div style="background-color: #e8f4f8; padding: 15px; border-radius: 5px; margin: 15px 0;">
              <h3 style="color: #34495e;">⏱️ Estimated Time Remaining</h3>
              <p style="font-size: 16px;">Based on current rate: ~{int((settings['target_users'] - total_users) * (time_elapsed / total_users) / 3600)} hours</p>
            </div>
            
            <p style="color: #7f8c8d; font-size: 14px; margin-top: 20px;">
              <em>Reddit Mental Health Data Collector</em>
            </p>
          </body>
        </html>
        """
        
        # Send via Resend API
        response = requests.post(
            'https://api.resend.com/emails',
            headers={
                'Authorization': f'Bearer {credentials["resend_api_key"]}',
                'Content-Type': 'application/json'
            },
            json={
                'from': 'Reddit Collector <noreply@info.moodmirror.online>',
                'to': [credentials['notification_email']],
                'subject': f'🎯 Reddit Collector Milestone: {milestone} Users Collected!',
                'html': html
            },
            timeout=10
        )
        
        if response.status_code == 200:
            print(f"   📧 Email notification sent to {credentials['notification_email']}")
        else:
            print(f"   ⚠️  Failed to send email: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"   ⚠️  Email notification error: {e}")


def send_completion_email(total_users, total_posts, avg_posts, avg_sentiment, avg_mh_participation, 
                         total_time, candidates_checked, candidates_rejected):
    """
    Send email notification when data collection is completed using Resend API
    """
    if 'resend_api_key' not in credentials or 'notification_email' not in credentials:
        print("   ⚠️  Completion email skipped - Resend API key or email not configured")
        return
    
    try:
        hours = int(total_time // 3600)
        minutes = int((total_time % 3600) // 60)
        seconds = int(total_time % 60)
        
        # HTML body
        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif;">
            <h2 style="color: #27ae60;">🎉 Data Collection Completed!</h2>
            
            <div style="background-color: #d4edda; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #28a745;">
              <h3 style="color: #155724;">✅ Collection Summary</h3>
              <ul style="font-size: 16px; line-height: 1.8;">
                <li><strong>Total Users Collected:</strong> {total_users} / {settings['target_users']}</li>
                <li><strong>Total Posts Collected:</strong> {total_posts:,}</li>
                <li><strong>Average Posts per User:</strong> {avg_posts:.1f}</li>
                <li><strong>Success Rate:</strong> {total_users/max(candidates_checked,1)*100:.1f}%</li>
              </ul>
            </div>
            
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
              <h3 style="color: #34495e;">📊 Dataset Quality</h3>
              <ul style="font-size: 16px; line-height: 1.8;">
                <li><strong>Average Sentiment:</strong> {avg_sentiment:.3f}</li>
                <li><strong>Average MH Participation:</strong> {avg_mh_participation:.1%}</li>
                <li><strong>Candidates Checked:</strong> {candidates_checked}</li>
                <li><strong>Candidates Rejected:</strong> {candidates_rejected}</li>
              </ul>
            </div>
            
            <div style="background-color: #e8f4f8; padding: 15px; border-radius: 5px; margin: 15px 0;">
              <h3 style="color: #34495e;">⏱️ Time Statistics</h3>
              <ul style="font-size: 16px; line-height: 1.8;">
                <li><strong>Total Time:</strong> {hours}h {minutes}m {seconds}s</li>
                <li><strong>Average Time per User:</strong> {total_time/total_users:.1f} seconds</li>
                <li><strong>Posts Collected per Hour:</strong> {(total_posts/(total_time/3600)):.1f}</li>
              </ul>
            </div>
            
            <p style="color: #7f8c8d; font-size: 14px; margin-top: 20px;">
              <em>Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</em>
            </p>
          </body>
        </html>
        """
        
        # Send via Resend API
        response = requests.post(
            'https://api.resend.com/emails',
            headers={
                'Authorization': f'Bearer {credentials["resend_api_key"]}',
                'Content-Type': 'application/json'
            },
            json={
                'from': 'Reddit Collector <noreply@info.moodmirror.online>',
                'to': [credentials['notification_email']],
                'subject': '🎉 Reddit Data Collection Completed!',
                'html': html
            },
            timeout=10
        )
        
        if response.status_code == 200:
            print(f"\n📧 Completion email sent to {credentials['notification_email']}")
        else:
            print(f"\n⚠️  Failed to send completion email: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"\n⚠️  Completion email error: {e}")


def extract_features(posts):
    """
    Extract features needed for your model
    Returns: dictionary of features
    """
    # Temporal features
    timestamps = [p['timestamp'] for p in posts]
    time_span_days = (max(timestamps) - min(timestamps)) / 86400
    posting_frequency = len(posts) / time_span_days
    
    # Get posting hours
    hours = [datetime.fromtimestamp(ts).hour for ts in timestamps]
    late_night_start = settings.get('late_night_hour_start', 0)
    late_night_end = settings.get('late_night_hour_end', 6)
    late_night_posts = sum(1 for h in hours if late_night_start <= h < late_night_end)
    late_night_ratio = late_night_posts / len(posts)
    
    # Sentiment analysis
    sentiments = [sentiment_analyzer.polarity_scores(p['text']) for p in posts]
    avg_sentiment = sum(s['compound'] for s in sentiments) / len(sentiments)
    negative_posts = sum(1 for s in sentiments if s['compound'] < -0.05)
    negative_ratio = negative_posts / len(posts)
    
    # Linguistic features
    all_text = ' '.join(p['text'] for p in posts).lower()
    words = all_text.split()
    
    # First-person pronouns (depression indicator)
    first_person_count = sum(1 for w in words if w in ['i', 'me', 'my', 'mine', 'myself'])
    first_person_ratio = first_person_count / len(words) if words else 0
    
    # Engagement features
    avg_score = sum(p['score'] for p in posts) / len(posts)
    
    # Community features
    subreddits = [p['subreddit'] for p in posts]
    unique_subreddits = len(set(subreddits))
    
    # Use mental health subs from config
    mh_posts = sum(1 for s in subreddits if s.lower() in mental_health_subs)
    mh_ratio = mh_posts / len(posts)
    
    # Calculate cold start features
    confidence_score = calculate_confidence_score(len(posts))
    temporal_consistency = calculate_temporal_consistency(posts)
    baseline_stability = calculate_baseline_stability(posts) if len(posts) >= 20 else 0.0
    
    # All collected users are full_personalization (sufficient data)
    cold_start_phase = 'fully_personalized'
    
    features = {
        'total_posts': len(posts),
        'time_span_days': round(time_span_days, 2),
        'posting_frequency': round(posting_frequency, 2),
        'late_night_ratio': round(late_night_ratio, 3),
        'avg_sentiment': round(avg_sentiment, 3),
        'negative_post_ratio': round(negative_ratio, 3),
        'first_person_pronoun_ratio': round(first_person_ratio, 3),
        'avg_score': round(avg_score, 2),
        'unique_subreddits': unique_subreddits,
        'mental_health_participation': round(mh_ratio, 3),
        # Cold start features
        'confidence_score': round(confidence_score, 3),
        'cold_start_phase': cold_start_phase,
        'temporal_consistency': round(temporal_consistency, 3),
        'baseline_stability': round(baseline_stability, 3)
    }
    
    # Add z-score features if available
    z_score_features = calculate_z_scores(posts)
    if z_score_features:
        features['user_mean_sentiment'] = round(z_score_features['user_mean_sentiment'], 3)
        features['user_std_sentiment'] = round(z_score_features['user_std_sentiment'], 3)
        features['max_z_score'] = round(z_score_features['max_z_score'], 3)
        features['deviations_z_gt_2'] = z_score_features['deviations_z_gt_2']
    
    return features


# ============================================================================
# MAIN COLLECTION LOOP
# ============================================================================

print("\n" + "="*70)
print("🚀 STARTING DATA COLLECTION")
print("="*70)

# Start timing
start_time = time.time()

collected_users = []
candidates_checked = 0
candidates_rejected = 0

# Try to load existing data
try:
    with open('data/collected_users.json', 'r') as f:
        collected_users = json.load(f)
    print(f"\n📂 Found existing data: {len(collected_users)} users already collected")
except:
    print("\n📂 No existing data found, starting fresh")

# Discover candidate users
print("\n--- PHASE 1: DISCOVERING CANDIDATES ---")
all_candidates = set()

# Memory optimization: Build already collected set first
already_collected = {u['username_hash'] for u in collected_users}

for subreddit in config['subreddits_to_search']:
    for sort_method in config['sort_methods']:
        users = get_users_from_subreddit(
            subreddit, 
            sort_method, 
            config['posts_to_scan_per_subreddit']
        )
        all_candidates.update(users)
        
        time.sleep(2)  # Be nice to Reddit

# Remove already collected users (convert to list for iteration)
candidates_to_check = [u for u in all_candidates 
                      if hashlib.sha256(u.encode()).hexdigest()[:16] not in already_collected]

# Free up memory
del all_candidates

print(f"\n📊 Discovery complete:")
print(f"   Found: {len(candidates_to_check) + len(already_collected)} total candidates")
print(f"   Already collected: {len(already_collected)} users")
print(f"   New to check: {len(candidates_to_check)} users")

# Send startup email with candidate info using Resend API
try:
    if 'resend_api_key' in credentials and 'notification_email' in credentials:
        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif;">
            <h2 style="color: #3498db;">🚀 Data Collection Started!</h2>
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px;">
              <h3>Collection Parameters:</h3>
              <ul style="font-size: 16px; line-height: 1.8;">
                <li><strong>Target Users:</strong> {settings['target_users']}</li>
                <li><strong>Min Posts per User:</strong> {settings['min_posts_per_user']}</li>
                <li><strong>Min MH Participation:</strong> {settings['min_mh_participation_ratio']:.0%}</li>
                <li><strong>Sentiment Range:</strong> -0.6 to 0.25</li>
                <li><strong>Baseline Stability:</strong> ≥{settings['min_baseline_stability']}</li>
              </ul>
            </div>
            <div style="background-color: #e8f4f8; padding: 15px; border-radius: 5px; margin-top: 15px;">
              <h3>Candidate Discovery:</h3>
              <ul style="font-size: 16px; line-height: 1.8;">
                <li><strong>Total Candidates Found:</strong> {len(candidates_to_check) + len(already_collected)}</li>
                <li><strong>Already Collected:</strong> {len(already_collected)}</li>
                <li><strong>New to Check:</strong> {len(candidates_to_check)}</li>
              </ul>
            </div>
            <p style="color: #7f8c8d; margin-top: 20px;">Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
          </body>
        </html>
        """
        
        response = requests.post(
            'https://api.resend.com/emails',
            headers={
                'Authorization': f'Bearer {credentials["resend_api_key"]}',
                'Content-Type': 'application/json'
            },
            json={
                'from': 'Reddit Collector <noreply@info.moodmirror.online>',
                'to': [credentials['notification_email']],
                'subject': '🚀 Reddit Data Collection Started!',
                'html': html
            },
            timeout=10
        )
        
        if response.status_code == 200:
            print("   📧 Startup email sent via Resend\n")
        else:
            print(f"   ⚠️  Failed to send startup email: {response.status_code}\n")
    else:
        print("   ⚠️  Resend API key not configured, skipping startup email\n")
except Exception as e:
    print(f"   ⚠️  Could not send startup email: {e}\n")

# Collection loop
print("\n--- PHASE 2: COLLECTING USER DATA ---")
print(f"Target: {settings['target_users']} users\n")

for username in candidates_to_check:
    # Stop if we hit target
    if len(collected_users) >= settings['target_users']:
        print(f"\n🎯 Target reached! Collected {len(collected_users)} users")
        break
    
    candidates_checked += 1
    # Generate anonymous ID immediately
    username_hash = hashlib.sha256(username.encode()).hexdigest()[:16]
    temp_user_id = f"candidate_{candidates_checked}"
    print(f"[{candidates_checked}] Checking: {temp_user_id}")
    
    # Collect posts
    posts = collect_user_posts(username, settings['time_window_days'])
    
    if not posts:
        print(f"   ⏭️  No posts found, skipping")
        candidates_rejected += 1
        continue
    
    # Quality check
    passed, reason = check_user_quality(posts)
    
    if not passed:
        print(f"   ⏭️  {reason}")
        candidates_rejected += 1
        continue
    
    # NEW: Validate sentiment distribution
    sentiment_valid, sentiment_reason, avg_sentiment = validate_sentiment_distribution(posts)
    if not sentiment_valid:
        print(f"   ⏭️  {sentiment_reason}")
        candidates_rejected += 1
        continue
    else:
        print(f"   ✅ Sentiment validated: avg={avg_sentiment:.3f}")
    
    # Extract features
    features = extract_features(posts)
    
    # Check if user has minimum posts (already checked in check_user_quality, but double-check)
    post_count = len(posts)
    required_posts = settings.get('min_posts_per_user', 30)
    if post_count < required_posts:
        print(f"   ⏭️  Only {post_count} posts (need {required_posts}+ for reliable baselines)")
        candidates_rejected += 1
        continue

    # Calculate baseline stability for metadata
    baseline_stability = calculate_baseline_stability(posts) if len(posts) >= 20 else 0.0
    
    # Use already generated anonymous ID
    user_id = f"user_{len(collected_users)+1:04d}"
    
    # Save user data (full_personalization focus)
    user_data = {
        'user_id': user_id,
        'username_hash': username_hash,
        'collection_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'posts': posts,
        'features': features,
        'metadata': {
            'post_count': len(posts),
            'baseline_stability': round(baseline_stability, 3),
            'temporal_consistency': features.get('temporal_consistency', 0),
            'category': 'full_personalization'
        }
    }
    
    collected_users.append(user_data)
    
    print(f"   ✅ COLLECTED! ({len(posts)} posts, full_personalization) - Total: {len(collected_users)}/{settings['target_users']}")

    
    # Save after each user (in case of interruption)
    with open('data/collected_users.json', 'w') as f:
        json.dump(collected_users, f, indent=2)
    
    # Send email notification at milestones (configurable)
    email_milestone = settings.get('email_milestone_frequency', 100)
    if len(collected_users) % email_milestone == 0:
        total_posts = sum(u['features']['total_posts'] for u in collected_users)
        avg_posts = total_posts / len(collected_users)
        avg_sentiment = sum(u['features']['avg_sentiment'] for u in collected_users) / len(collected_users)
        time_elapsed = time.time() - start_time
        
        send_email_notification(
            milestone=len(collected_users),
            total_users=len(collected_users),
            avg_posts=avg_posts,
            avg_sentiment=avg_sentiment,
            time_elapsed=time_elapsed
        )
    
    # Rate limiting (configurable)
    rate_limit = settings.get('rate_limit_seconds', 2)
    time.sleep(rate_limit)

# ===============================================================F=============
# FINAL SUMMARY
# ============================================================================

print("\n" + "="*70)
print("📊 COLLECTION COMPLETE")
print("="*70)
print(f"\n✅ Successfully collected: {len(collected_users)} users")
print(f"📊 Candidates checked: {candidates_checked}")
print(f"❌ Candidates rejected: {candidates_rejected}")
print(f"✓ Success rate: {len(collected_users)/max(candidates_checked,1)*100:.1f}%")

# Calculate statistics
if collected_users:
    total_posts = sum(u['features']['total_posts'] for u in collected_users)
    avg_posts = total_posts / len(collected_users)
    avg_sentiment = sum(u['features']['avg_sentiment'] for u in collected_users) / len(collected_users)
    avg_mh_participation = sum(u['features']['mental_health_participation'] for u in collected_users) / len(collected_users)
    
    print(f"\n📈 Dataset Statistics:")
    print(f"   Total posts collected: {total_posts}")
    print(f"   Average posts per user: {avg_posts:.1f}")
    print(f"   Average sentiment: {avg_sentiment:.3f}")
    print(f"   Average MH subreddit participation: {avg_mh_participation:.1%}")
    
    # NEW: Sentiment distribution validation
    sentiments = [user['features']['avg_sentiment'] for user in collected_users]
    mh_participation_ratios = [user['features']['mental_health_participation'] for user in collected_users]
    print(f"\n🎯 Data Quality Validation:")
    print(f"   Sentiment range: {min(sentiments):.3f} to {max(sentiments):.3f}")
    print(f"   Users with negative sentiment: {sum(1 for s in sentiments if s < 0)} ({sum(1 for s in sentiments if s < 0)/len(sentiments):.1%})")
    print(f"   Average MH participation: {avg_mh_participation:.1%}")
    print(f"   Users meeting 40%+ MH threshold: {sum(1 for ratio in mh_participation_ratios if ratio >= 0.4)} ({sum(1 for ratio in mh_participation_ratios if ratio >= 0.4)/len(mh_participation_ratios):.1%})")

print(f"\n💾 Data saved to: data/collected_users.json")

# Calculate population baseline statistics
if collected_users:
    def calculate_population_baseline(collected_users):
        """
        Calculate population-level statistics for personalization
        """
        all_sentiments = []
        all_frequencies = []
        all_late_night_ratios = []
        
        for user in collected_users:
            all_sentiments.append(user['features']['avg_sentiment'])
            all_frequencies.append(user['features']['posting_frequency'])
            all_late_night_ratios.append(user['features']['late_night_ratio'])
        
        population_baseline = {
            'population_mean_sentiment': float(np.mean(all_sentiments)),
            'population_std_sentiment': float(np.std(all_sentiments)),
            'population_mean_frequency': float(np.mean(all_frequencies)),
            'population_std_frequency': float(np.std(all_frequencies)),
            'population_mean_late_night': float(np.mean(all_late_night_ratios)),
            'population_std_late_night': float(np.std(all_late_night_ratios))
        }
        
        return population_baseline
    
    population_baseline = calculate_population_baseline(collected_users)
    with open('data/population_baseline.json', 'w', encoding='utf-8') as f:
        json.dump(population_baseline, f, indent=2)
    print("💾 Population baseline saved to: data/population_baseline.json")

# Calculate total time
total_time = time.time() - start_time
hours = int(total_time // 3600)
minutes = int((total_time % 3600) // 60)
seconds = int(total_time % 60)

print("\n⏱️ Collection Time Statistics:")
print(f"   Total time: {hours}h {minutes}m {seconds}s")
print(f"   Average time per user: {total_time/len(collected_users):.1f} seconds")
print(f"   Posts collected per hour: {(total_posts/(total_time/3600)):.1f}")

# Send completion email notification
if collected_users:
    send_completion_email(
        total_users=len(collected_users),
        total_posts=total_posts,
        avg_posts=avg_posts,
        avg_sentiment=avg_sentiment,
        avg_mh_participation=avg_mh_participation,
        total_time=total_time,
        candidates_checked=candidates_checked,
        candidates_rejected=candidates_rejected
    )

# Dataset composition statistics
if collected_users:
    print(f"\n🔬 Dataset Composition:")
    min_posts = settings.get('min_posts_per_user', 30)
    print(f"   All users have {min_posts}+ posts (full personalization)")
    print(f"   Post count distribution:")
    post_counts = [u['metadata']['post_count'] for u in collected_users]
    print(f"     {min_posts}-50 posts: {sum(1 for count in post_counts if min_posts <= count <= 50)}")
    print(f"     51-80 posts: {sum(1 for count in post_counts if 51 <= count <= 80)}")
    print(f"     81+ posts: {sum(1 for count in post_counts if count > 80)}")

# write all the print statements to a log file
with open('data/collection_log.txt', 'w', encoding='utf-8') as log_file:
    log_file.write("\n" + "="*70 + "\n")
    log_file.write("📊 COLLECTION COMPLETE\n")
    log_file.write("="*70 + "\n")
    log_file.write(f"\n✅ Successfully collected: {len(collected_users)} users\n")
    log_file.write(f"📊 Candidates checked: {candidates_checked}\n")
    log_file.write(f"❌ Candidates rejected: {candidates_rejected}\n")
    log_file.write(f"✓ Success rate: {len(collected_users)/max(candidates_checked,1)*100:.1f}%\n")

    if collected_users:
        log_file.write(f"\n📈 Dataset Statistics:\n")
        log_file.write(f"   Total posts collected: {total_posts}\n")
        log_file.write(f"   Average posts per user: {avg_posts:.1f}\n")
        log_file.write(f"   Average sentiment: {avg_sentiment:.3f}\n")
        log_file.write(f"   Average MH subreddit participation: {avg_mh_participation:.1%}\n")
        
        # NEW: Sentiment distribution validation
        sentiments = [user['features']['avg_sentiment'] for user in collected_users]
        mh_participation_ratios = [user['features']['mental_health_participation'] for user in collected_users]
        log_file.write(f"\n🎯 Data Quality Validation:\n")
        log_file.write(f"   Sentiment range: {min(sentiments):.3f} to {max(sentiments):.3f}\n")
        log_file.write(f"   Users with negative sentiment: {sum(1 for s in sentiments if s < 0)} ({sum(1 for s in sentiments if s < 0)/len(sentiments):.1%})\n")
        log_file.write(f"   Average MH participation: {avg_mh_participation:.1%}\n")
        log_file.write(f"   Users meeting 40%+ MH threshold: {sum(1 for ratio in mh_participation_ratios if ratio >= 0.4)} ({sum(1 for ratio in mh_participation_ratios if ratio >= 0.4)/len(mh_participation_ratios):.1%})\n")
        
        log_file.write(f"\n⏱️ Collection Time Statistics:\n")
        log_file.write(f"   Total time: {hours}h {minutes}m {seconds}s\n")
        log_file.write(f"   Average time per user: {total_time/len(collected_users):.1f} seconds\n")
        log_file.write(f"   Posts collected per hour: {(total_posts/(total_time/3600)):.1f}\n")
        
        # Dataset composition statistics
        min_posts = settings.get('min_posts_per_user', 30)
        log_file.write(f"\n🔬 Dataset Composition:\n")
        log_file.write(f"   All users have {min_posts}+ posts (full personalization)\n")
        log_file.write(f"   Post count distribution:\n")
        post_counts = [u['metadata']['post_count'] for u in collected_users]
        log_file.write(f"     {min_posts}-50 posts: {sum(1 for count in post_counts if min_posts <= count <= 50)}\n")
        log_file.write(f"     51-80 posts: {sum(1 for count in post_counts if 51 <= count <= 80)}\n")
        log_file.write(f"     81+ posts: {sum(1 for count in post_counts if count > 80)}\n")
    else:
        log_file.write("\nNo users were collected.\n")

print(f"\n✨ Done!\n")