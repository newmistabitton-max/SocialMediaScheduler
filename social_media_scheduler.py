import csv
import os
from datetime import datetime
import time
import tweepy
import requests
from dotenv import load_dotenv
import argparse

# Load environment variables
load_dotenv()

# ---------- Configuration ----------
TWITTER_API_KEY = os.environ.get('TWITTER_API_KEY', '')
TWITTER_API_SECRET = os.environ.get('TWITTER_API_SECRET', '')
TWITTER_ACCESS_TOKEN = os.environ.get('TWITTER_ACCESS_TOKEN', '')
TWITTER_ACCESS_SECRET = os.environ.get('TWITTER_ACCESS_SECRET', '')
DRY_RUN = os.environ.get('DRY_RUN', 'True').lower() == 'true'

# ---------- Platform Clients ----------
def get_twitter_client():
    """Initialize and return Twitter client"""
    try:
        auth = tweepy.OAuthHandler(TWITTER_API_KEY, TWITTER_API_SECRET)
        auth.set_access_token(TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET)
        return tweepy.API(auth, wait_on_rate_limit=True)
    except Exception as e:
        print(f"Error initializing Twitter client: {e}")
        return None

# ---------- Enhanced Logging ----------
def ensure_log_files():
    """Ensure log files exist with headers"""
    logs = [
        ('success_log.csv', ['Timestamp', 'Platform', 'Content Preview', 'Status', 'Post ID']),
        ('error_log.csv', ['Timestamp', 'Platform', 'Content Preview', 'Error Message', 'Resolved']),
        ('analytics_log.csv', ['Timestamp', 'Platform', 'Post ID', 'Likes', 'Retweets', 'Replies', 'Impressions'])
    ]
    
    for filename, headers in logs:
        if not os.path.exists(filename):
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)

def log_success(platform, content, post_id=None):
    with open("success_log.csv", "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now(), platform, content[:100], "Posted ✅", post_id or "N/A"])

def log_error(platform, content, error_message):
    with open("error_log.csv", "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now(), platform, content[:100], error_message, "No"])

def log_analytics(platform, post_id, metrics):
    with open("analytics_log.csv", "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now(), platform, post_id] + list(metrics.values()))

# ---------- Platform Publishing Functions ----------
def publish_tweet(content, dry_run=False):
    """Publish a tweet to Twitter/X"""
    if dry_run:
        print(f"DRY RUN → Would tweet: {content}")
        return "dry_run", None
    
    try:
        twitter_client = get_twitter_client()
        if not twitter_client:
            return "error", "Twitter client not initialized"
        
        if len(content) > 280:
            content = content[:277] + "..."
        
        tweet = twitter_client.update_status(content)
        return "success", tweet.id_str
    except Exception as e:
        return "error", str(e)

def publish_thread(contents, dry_run=False):
    """Publish a thread to Twitter/X"""
    if dry_run:
        print(f"DRY RUN → Would post thread with {len(contents)} tweets")
        for i, content in enumerate(contents):
            print(f"  Tweet {i+1}: {content}")
        return ["dry_run"] * len(contents), None
    
    try:
        twitter_client = get_twitter_client()
        if not twitter_client:
            return ["error"], "Twitter client not initialized"
        
        tweet_ids = []
        previous_tweet_id = None
        
        for i, content in enumerate(contents):
            if len(content) > 280:
                content = content[:277] + "..."
            
            if i == 0:
                tweet = twitter_client.update_status(content)
                tweet_ids.append(tweet.id_str)
                previous_tweet_id = tweet.id_str
            else:
                time.sleep(1)
                tweet = twitter_client.update_status(
                    status=content,
                    in_reply_to_status_id=previous_tweet_id,
                    auto_populate_reply_metadata=True
                )
                tweet_ids.append(tweet.id_str)
                previous_tweet_id = tweet.id_str
        
        return ["success"] * len(contents), tweet_ids
    except Exception as e:
        return ["error"], str(e)

# ---------- Safe publish ----------
def safe_publish(platform, content, row_index, dry_run):
    try:
        if dry_run:
            print(f"DRY RUN → Would post to {platform}: {content}")
            return "Dry Run ✅"

        post_id = None
        
        if platform == "X Thread":
            thread_parts = [part.strip() for part in content.split("|||") if part.strip()]
            if not thread_parts:
                raise ValueError("Thread content is empty after splitting")
            
            results, ids_or_error = publish_thread(thread_parts, dry_run)
            
            if "error" in results:
                raise Exception(f"Thread posting failed: {ids_or_error}")
            
            post_id = ",".join(ids_or_error) if isinstance(ids_or_error, list) else "Unknown"
            
        elif platform == "X Tweet":
            result, id_or_error = publish_tweet(content, dry_run)
            
            if result == "error":
                raise Exception(f"Tweet posting failed: {id_or_error}")
            
            post_id = id_or_error if result == "success" else "DryRun"
            
        else:
            raise ValueError("Unsupported platform: " + platform)

        log_success(platform, content, post_id)
        return "Posted ✅"

    except Exception as e:
        log_error(platform, content, str(e))
        return "Error ❌ (will retry)"

# ---------- Content Validation ----------
def validate_content_calendar(rows):
    """Validate content calendar entries"""
    valid_platforms = ["X Tweet", "X Thread"]
    errors = []
    warnings = []
    
    for i, row in enumerate(rows, start=2):
        if len(row) < 4:
            errors.append(f"Row {i}: Insufficient columns")
            continue
            
        date_planned, platform, content, status = row[:4]
        
        try:
            datetime.strptime(date_planned, "%Y-%m-%d").date()
        except:
            errors.append(f"Row {i}: Invalid date format {date_planned}. Use YYYY-MM-DD")
        
        if platform not in valid_platforms:
            errors.append(f"Row {i}: Invalid platform {platform}. Must be one of {valid_platforms}")
        
        if not content or not content.strip():
            errors.append(f"Row {i}: Content is empty")
        elif platform == "X Tweet" and len(content) > 280:
            warnings.append(f"Row {i}: Tweet content exceeds 280 characters ({len(content)})")
        elif platform == "X Thread":
            parts = [part.strip() for part in content.split("|||") if part.strip()]
            if not parts:
                errors.append(f"Row {i}: Thread content is empty after splitting with |||")
            for j, part in enumerate(parts):
                if len(part) > 280:
                    warnings.append(f"Row {i}, Thread part {j+1}: Exceeds 280 characters ({len(part)})")
    
    return errors, warnings

# ---------- Analytics Tracking ----------
def track_analytics():
    """Track performance of previous posts"""
    try:
        twitter_client = get_twitter_client()
        if not twitter_client:
            print("Cannot track analytics - Twitter client not available")
            return
        
        post_ids = []
        with open("success_log.csv", "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)
            for row in reader:
                if row[4] and row[4] != "N/A" and row[4] != "DryRun":
                    post_ids.append((row[1], row[4]))
        
        for platform, post_id in post_ids:
            if platform in ["X Tweet", "X Thread"]:
                try:
                    tweet = twitter_client.get_status(post_id, tweet_mode="extended")
                    metrics = {
                        "likes": tweet.favorite_count,
                        "retweets": tweet.retweet_count,
                        "replies": 0,
                        "impressions": getattr(tweet, 'impression_count', 'N/A')
                    }
                    log_analytics(platform, post_id, metrics)
                except Exception as e:
                    print(f"Error getting analytics for {post_id}: {e}")
    
    except Exception as e:
        print(f"Error in analytics tracking: {e}")

# ---------- Auto Scheduler ----------
def auto_schedule_publish():
    dry_run = DRY_RUN
    today = datetime.now().date()
    
    print(f"Running social media scheduler (Dry Run: {dry_run})")
    print(f"Current time: {datetime.now()}")
    
    ensure_log_files()
    
    if not os.path.exists("content_calendar.csv"):
        print("Error: content_calendar.csv not found")
        print("Creating a sample content_calendar.csv file...")
        with open("content_calendar.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date_planned", "platform", "content", "status"])
            writer.writerow(["2023-12-15", "X Tweet", "This is a test tweet - replace with your content!", "Post Now"])
            writer.writerow(["2023-12-15", "X Thread", "First part of my thread|||Second part with more details|||Final part with a call to action", "Post Now"])
        print("Sample content_calendar.csv created. Please edit it with your content.")
        return
    
    with open("content_calendar.csv", "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
    
    if not reader or len(reader) < 2:
        print("Content calendar is empty")
        return
    
    header, rows = reader[0], reader[1:]
    
    errors, warnings = validate_content_calendar(rows)
    
    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"  ⚠️  {warning}")
    
    if errors:
        print("\nErrors found in content calendar:")
        for error in errors:
            print(f"  ❌ {error}")
        print("Fix errors before proceeding")
        return
    
    posted_count = 0
    for i, row in enumerate(rows, start=1):
        if len(row) < 4:
            continue
            
        date_planned, platform, content, status = row[:4]
        
        try:
            planned_date = datetime.strptime(date_planned, "%Y-%m-%d").date()
        except:
            continue

        if status == "Post Now" and planned_date == today:
            print(f"\nProcessing row {i+1}: {platform}")
            result = safe_publish(platform, content, i+1, dry_run)
            rows[i-1][3] = result
            
            if "Posted" in result:
                posted_count += 1
            elif "Error" in result:
                print(f"  Failed to post: {content[:50]}...")

    with open("content_calendar.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    
    if not dry_run and posted_count > 0:
        print("\nTracking analytics for previous posts...")
        track_analytics()
    
    print(f"\n✅ Auto-schedule complete. Posted {posted_count} items.")

# ---------- Post Now Function ----------
def post_now():
    """Manually post content immediately regardless of schedule"""
    dry_run = DRY_RUN
    
    if not os.path.exists("content_calendar.csv"):
        print("Error: content_calendar.csv not found")
        return
    
    with open("content_calendar.csv", "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
    header, rows = reader[0], reader[1:]
    
    print("Select content to post immediately:")
    for i, row in enumerate(rows, start=1):
        if len(row) >= 4:
            print(f"{i}. {row[1]}: {row[2][:50]}... (Status: {row[3]})")
    
    try:
        choice = int(input("\nEnter row number to post: ")) - 1
        if choice < 0 or choice >= len(rows):
            print("Invalid selection")
            return
        
        row = rows[choice]
        if len(row) < 4:
            print("Invalid row format")
            return
            
        date_planned, platform, content, status = row[:4]
        print(f"Posting: {platform} - {content[:50]}...")
        
        result = safe_publish(platform, content, choice+2, dry_run)
        rows[choice][3] = result
        
        with open("content_calendar.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
        
        print(f"Result: {result}")
        
    except ValueError:
        print("Please enter a valid number")
    except Exception as e:
        print(f"Error: {e}")

# ---------- Setup Function ----------
def setup():
    """Setup the application"""
    print("Setting up Social Media Scheduler...")
    print()
    
    # Create virtual environment
    print("Creating virtual environment...")
    os.system("python -m venv social_media_env")
    
    # Install requirements
    print("Installing required packages...")
    os.system("social_media_env\\Scripts\\pip install tweepy requests python-dotenv")
    
    # Create sample files
    print("Creating sample files...")
    
    # Create content_calendar.csv if it doesn't exist
    if not os.path.exists("content_calendar.csv"):
        with open("content_calendar.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date_planned", "platform", "content", "status"])
            writer.writerow(["2023-12-15", "X Tweet", "This is a test tweet - replace with your content!", "Post Now"])
            writer.writerow(["2023-12-15", "X Thread", "First part of my thread|||Second part with more details|||Final part with a call to action", "Post Now"])
    
    # Create .env file if it doesn't exist
    if not os.path.exists(".env"):
        with open(".env", "w", encoding="utf-8") as f:
            f.write("# Twitter API Configuration\n")
            f.write("# Get these from https://developer.twitter.com\n")
            f.write("TWITTER_API_KEY=your_api_key_here\n")
            f.write("TWITTER_API_SECRET=your_api_secret_here\n")
            f.write("TWITTER_ACCESS_TOKEN=your_access_token_here\n")
            f.write("TWITTER_ACCESS_SECRET=your_access_token_secret_here\n")
            f.write("\n# App Configuration\n")
            f.write("DRY_RUN=True\n")
    
    print()
    print("Setup complete!")
    print()
    print("NEXT STEPS:")
    print("1. Get API keys from Twitter Developer Portal")
    print("2. Edit .env with your actual API keys")
    print("3. Run: python social_media_scheduler.py --dry-run")
    print()

# ---------- Main Execution ----------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Social Media Scheduler')
    parser.add_argument('--post-now', action='store_true', help='Manually post content now')
    parser.add_argument('--dry-run', action='store_true', help='Run without actually posting')
    parser.add_argument('--live-run', action='store_true', help='Run with actual posting')
    parser.add_argument('--setup', action='store_true', help='Setup the application')
    
    args = parser.parse_args()
    
    if args.dry_run:
        os.environ['DRY_RUN'] = 'True'
    elif args.live_run:
        os.environ['DRY_RUN'] = 'False'
    
    if args.setup:
        setup()
    elif args.post_now:
        post_now()
    else:
        auto_schedule_publish()