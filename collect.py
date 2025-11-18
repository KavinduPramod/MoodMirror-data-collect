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
        
        # Sort by time
        posts.sort(key=lambda x: x['timestamp'])
        
        return posts
        
    except Exception as e:
        print(f"      Error collecting {username}: {e}")
        return []


def calculate_dynamic_window(posting_frequency):
    """
    Calculate dynamic time window based on posting frequency
    High frequency (>1 post/day): 21-day window
    Medium frequency (3-7 posts/week): 30-45 day window
    Low frequency (<3 posts/week): 45-60 day window
    """
    if posting_frequency > 1.0:  # >1 post/day
        return 21
    elif posting_frequency >= 0.43:  # 3+ posts/week
        return 35
    else:  # <3 posts/week
        return 50


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
    Calculate confidence score for cold start problem
    Returns: confidence_score (0-1)
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
    
    if time_span_days < 7:
        return False, f"All posts within {time_span_days:.1f} days (need 7+ days spread)"
    
    # Check 3: Average text length
    avg_length = sum(len(p['text']) for p in posts) / len(posts)
    
    if avg_length < settings['min_text_length']:
        return False, f"Posts too short (avg {avg_length:.0f} chars)"
    
    # Check 4: Subreddit diversity
    subreddits = set(p['subreddit'] for p in posts)
    
    if len(subreddits) < settings['min_subreddits']:
        return False, f"Only posts in {len(subreddits)} subreddit(s)"
    
    # Check 5: Mental health participation (NEW)
    mental_health_subs = ['depression', 'anxiety', 'mentalhealth', 'suicidewatch', 
                          'lonely', 'bipolarreddit', 'bpd', 'adhd', 'ocd', 'ptsd',
                          'addiction', 'edanonymous', 'socialanxiety', 'agoraphobia',
                          'panicattack', 'mentalillness', 'therapy', 'traumatoolbox',
                          'mentalhealthsupport', 'anxietyhelp', 'depressionhelp',
                          'healthanxiety', 'cptsd', 'askatherapist', 'stopselfharm',
                          'eating_disorders', 'psychosis', 'schizophrenia', 'dpdr']
    
    mh_posts = sum(1 for p in posts if p['subreddit'].lower() in mental_health_subs)
    mh_ratio = mh_posts / len(posts)
    
    if 'min_mh_posts' in settings and mh_posts < settings['min_mh_posts']:
        return False, f"Only {mh_posts} mental health posts (need {settings['min_mh_posts']})"
    
    if 'min_mh_participation_ratio' in settings and mh_ratio < settings['min_mh_participation_ratio']:
        return False, f"Only {mh_ratio:.1%} MH participation (need {settings['min_mh_participation_ratio']:.1%})"
    
    # Check 6: Baseline stability (for users with enough posts)
    if len(posts) >= 20 and 'min_baseline_stability' in settings:
        baseline_stability = calculate_baseline_stability(posts)
        if baseline_stability < settings['min_baseline_stability']:
            return False, f"Low baseline stability ({baseline_stability:.2f}, need {settings['min_baseline_stability']:.2f})"
    
    return True, "Passed all checks"


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
    late_night_posts = sum(1 for h in hours if 0 <= h < 6)
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
    
    mental_health_subs = ['depression', 'anxiety', 'mentalhealth', 'suicidewatch', 
                          'lonely', 'bipolarreddit', 'bpd', 'adhd']
    mh_posts = sum(1 for s in subreddits if s.lower() in mental_health_subs)
    mh_ratio = mh_posts / len(posts)
    
    # Calculate cold start features
    confidence_score = calculate_confidence_score(len(posts))
    temporal_consistency = calculate_temporal_consistency(posts)
    baseline_stability = calculate_baseline_stability(posts) if len(posts) >= 20 else 0.0
    
    # Determine cold start phase
    if confidence_score < 0.33:
        cold_start_phase = 'cold_start'
    elif confidence_score < 1.0:
        cold_start_phase = 'transition'
    else:
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

# Track category targets for stratified sampling
category_counts = {
    'cold_start': 0,
    'transition': 0,
    'full_personalization': 0
}

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

for subreddit in config['subreddits_to_search']:
    for sort_method in config['sort_methods']:
        users = get_users_from_subreddit(
            subreddit, 
            sort_method, 
            config['posts_to_scan_per_subreddit']
        )
        all_candidates.update(users)
        
        time.sleep(2)  # Be nice to Reddit

# Remove already collected users
already_collected = {u['username_hash'] for u in collected_users}
candidates_to_check = [u for u in all_candidates 
                      if hashlib.sha256(u.encode()).hexdigest()[:16] not in already_collected]

print(f"\n📊 Discovery complete:")
print(f"   Found: {len(all_candidates)} total candidates")
print(f"   Already collected: {len(already_collected)} users")
print(f"   New to check: {len(candidates_to_check)} users")

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
    
    # Extract features
    features = extract_features(posts)
    
    # Determine category based on post count for stratified sampling
    post_count = len(posts)
    if 'user_categories' in settings:
        if post_count < settings['user_categories']['transition']['min']:
            category = 'cold_start'
        elif post_count < settings['user_categories']['full_personalization']['min']:
            category = 'transition'
        else:
            category = 'full_personalization'
        
        # Check if category is full
        target_per_category = {
            'cold_start': settings['user_categories']['cold_start']['target_users'],
            'transition': settings['user_categories']['transition']['target_users'],
            'full_personalization': settings['user_categories']['full_personalization']['target_users']
        }
        
        if category_counts[category] >= target_per_category[category]:
            print(f"   ⏭️  Category '{category}' full ({category_counts[category]}/{target_per_category[category]}), skipping")
            candidates_rejected += 1
            continue
    
    # Calculate baseline stability for metadata
    baseline_stability = calculate_baseline_stability(posts) if len(posts) >= 20 else 0.0
    
    # Use already generated anonymous ID
    user_id = f"user_{len(collected_users)+1:04d}"
    
    # Save user data with cold start metadata
    user_data = {
        'user_id': user_id,
        'username_hash': username_hash,
        'collection_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'posts': posts,
        'features': features,
        'cold_start_metadata': {
            'post_count': len(posts),
            'confidence_score': features.get('confidence_score', 0),
            'cold_start_phase': features.get('cold_start_phase', 'unknown'),
            'baseline_stability': round(baseline_stability, 3),
            'temporal_consistency': features.get('temporal_consistency', 0),
            'suitable_for_cold_start_testing': len(posts) < 30,
            'suitable_for_baseline_testing': len(posts) >= 30 and baseline_stability > 0.85,
            'category': category if 'user_categories' in settings else 'unknown'
        }
    }
    
    collected_users.append(user_data)
    
    # Increment category count
    if 'user_categories' in settings:
        category_counts[category] += 1
    
    print(f"   ✅ COLLECTED! ({len(posts)} posts, {category if 'user_categories' in settings else 'N/A'}) - Total: {len(collected_users)}/{settings['target_users']}")

    
    # Save after each user (in case of interruption)
    with open('data/collected_users.json', 'w') as f:
        json.dump(collected_users, f, indent=2)
    
    # Rate limiting
    time.sleep(2)

# ============================================================================
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

print(f"\n💾 Data saved to: data/collected_users.json")

# Calculate population baseline for cold start analysis
if collected_users:
    def calculate_population_baseline(collected_users):
        """
        Calculate population-level statistics for cold start comparison
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

# Cold start analysis statistics
if collected_users:
    cold_start_users = sum(1 for u in collected_users 
                          if u['cold_start_metadata']['cold_start_phase'] == 'cold_start')
    transition_users = sum(1 for u in collected_users 
                          if u['cold_start_metadata']['cold_start_phase'] == 'transition')
    full_users = sum(1 for u in collected_users 
                    if u['cold_start_metadata']['cold_start_phase'] == 'fully_personalized')
    
    avg_confidence = sum(u['cold_start_metadata']['confidence_score'] 
                        for u in collected_users) / len(collected_users)
    
    avg_stability = sum(u['cold_start_metadata']['baseline_stability'] 
                       for u in collected_users) / len(collected_users)
    
    suitable_for_cold_start = sum(1 for u in collected_users 
                                  if u['cold_start_metadata']['suitable_for_cold_start_testing'])
    
    suitable_for_baseline = sum(1 for u in collected_users 
                               if u['cold_start_metadata']['suitable_for_baseline_testing'])
    
    print("\n🔬 Cold Start Analysis Statistics:")
    print(f"   Cold start users (5-15 posts): {cold_start_users}")
    print(f"   Transition users (16-30 posts): {transition_users}")
    print(f"   Fully personalized users (31+ posts): {full_users}")
    print(f"   Average confidence score: {avg_confidence:.3f}")
    print(f"   Average baseline stability: {avg_stability:.3f}")
    print(f"   Users suitable for cold start testing: {suitable_for_cold_start}")
    print(f"   Users suitable for baseline testing: {suitable_for_baseline}")

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
        log_file.write(f"\n⏱️ Collection Time Statistics:\n")
        log_file.write(f"   Total time: {hours}h {minutes}m {seconds}s\n")
        log_file.write(f"   Average time per user: {total_time/len(collected_users):.1f} seconds\n")
        log_file.write(f"   Posts collected per hour: {(total_posts/(total_time/3600)):.1f}\n")
        
        # Cold start statistics
        cold_start_users = sum(1 for u in collected_users 
                              if u['cold_start_metadata']['cold_start_phase'] == 'cold_start')
        transition_users = sum(1 for u in collected_users 
                              if u['cold_start_metadata']['cold_start_phase'] == 'transition')
        full_users = sum(1 for u in collected_users 
                        if u['cold_start_metadata']['cold_start_phase'] == 'fully_personalized')
        avg_confidence = sum(u['cold_start_metadata']['confidence_score'] 
                            for u in collected_users) / len(collected_users)
        avg_stability = sum(u['cold_start_metadata']['baseline_stability'] 
                           for u in collected_users) / len(collected_users)
        suitable_for_cold_start = sum(1 for u in collected_users 
                                      if u['cold_start_metadata']['suitable_for_cold_start_testing'])
        suitable_for_baseline = sum(1 for u in collected_users 
                                   if u['cold_start_metadata']['suitable_for_baseline_testing'])
        
        log_file.write(f"\n🔬 Cold Start Analysis Statistics:\n")
        log_file.write(f"   Cold start users (5-15 posts): {cold_start_users}\n")
        log_file.write(f"   Transition users (16-30 posts): {transition_users}\n")
        log_file.write(f"   Fully personalized users (31+ posts): {full_users}\n")
        log_file.write(f"   Average confidence score: {avg_confidence:.3f}\n")
        log_file.write(f"   Average baseline stability: {avg_stability:.3f}\n")
        log_file.write(f"   Users suitable for cold start testing: {suitable_for_cold_start}\n")
        log_file.write(f"   Users suitable for baseline testing: {suitable_for_baseline}\n")
    else:
        log_file.write("\nNo users were collected.\n")

print(f"\n✨ Done!\n")