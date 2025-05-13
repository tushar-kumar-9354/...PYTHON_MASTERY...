import os
import django
from selenium import webdriver
from selenium.webdriver.chrome.service import Service 
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup

# === Django Setup ===
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pymastery.settings")
django.setup()

from core.models import Course, Lesson, Quiz, Question, Option

# === Chrome Setup ===
chrome_options = Options()
chrome_options.add_argument("--start-maximized")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--ignore-certificate-errors")

service = Service(r"C:\Users\Hp\PYMASTERY\example\chromedriver.exe")
driver = webdriver.Chrome(service=service, options=chrome_options)

# === GFG TOC Page ===
toc_url = "https://www.geeksforgeeks.org/python-programming-language-tutorial/"
driver.get(toc_url)

try:
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.XPATH, "//article"))
    )
    print("✅ TOC page loaded:", driver.title)
except TimeoutException:
    print("❌ TOC page timeout.")
    driver.quit()
    exit()

soup = BeautifulSoup(driver.page_source, "html.parser")
driver.quit()

article = soup.find("article")
if not article:
    print("❌ Article section not found.")
    exit()

# === Create Course ===
course, _ = Course.objects.get_or_create(
    title="Python by GFG",
    defaults={"description": "Auto-scraped Python content from GeeksforGeeks"}
)

# === Blocklist for irrelevant entries ===
ban_keywords = [
    'java', 'tensorflow', 'keras', 'xgboost', 'lightgbm', 'sqlalchemy',
    'rest', 'mongodb', 'django rest', 'api', 'pytorch', 'flask'
]

# === Extract tutorial links ===
links = article.find_all("a", href=True)
tutorials = []
for link in links:
    title = link.get_text(strip=True)
    href = link['href']
    if not title or not href.startswith("https://"):
        continue

    if any(bad in title.lower() for bad in ban_keywords):
        print(f"⏭️ Skipped (banned): {title}")
        continue

    tutorials.append((title, href))

print(f"🔗 Found {len(tutorials)} valid tutorials.")

# === Reopen browser for scraping ===
driver = webdriver.Chrome(service=service, options=chrome_options)

# === Scrape and Save Lessons + Quiz ===
for index, (title, href) in enumerate(tutorials):
    if Lesson.objects.filter(title=title).exists():
        print(f"⏭️ Skipped (duplicate title): {title}")
        continue

    print(f"\n[{index+1}/{len(tutorials)}] Scraping: {title} - {href}")
    try:
        driver.get(href)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//article"))
        )
        content_soup = BeautifulSoup(driver.page_source, "html.parser")
        content = content_soup.find("article")
        if not content:
            print("⚠️ No content found.")
            continue

        text = "\n\n".join(p.get_text(strip=True) for p in content.find_all(["p", "pre", "ul", "ol"]))
        if not text.strip() or Lesson.objects.filter(content=text.strip()).exists():
            print(f"⏭️ Skipped (empty or duplicate content): {title}")
            continue

        # === Save Lesson ===
        lesson = Lesson.objects.create(
            course=course,
            title=title[:200],
            content=text[:10000],
            order=index
        )
        print(f"✅ Saved Lesson: {title}")

        # === Create Quiz for Lesson ===
        quiz = Quiz.objects.create(
            lesson=lesson,
            title=f"{lesson.title} - Quiz",
            description="Auto-generated quiz for practice"
        )

        # === Add Sample Question and Options ===
        question = Question.objects.create(
            quiz=quiz,
            question_text="What is the primary topic of this lesson?"
        )

        Option.objects.create(question=question, option_text="Python Basics", is_correct=True)
        Option.objects.create(question=question, option_text="Java", is_correct=False)
        Option.objects.create(question=question, option_text="HTML/CSS", is_correct=False)
        Option.objects.create(question=question, option_text="C++", is_correct=False)

        print(f"✅ Quiz & Question added for: {title}")

    except Exception as e:
        print(f"❌ Error scraping {title}: {e}")
        continue

driver.quit()
print("\n🎉 Done! Lessons, quizzes, and questions added. View at http://127.0.0.1:8000/courses/")
