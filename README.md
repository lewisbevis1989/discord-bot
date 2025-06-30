# Discord Bot on Render

### ✅ Files Included
- `main.py`: Your bot script
- `requirements.txt`: Python libraries
- `render.yaml`: Render deployment config

### 🚀 How to Deploy
1. Upload these files to a GitHub repo
2. Go to https://render.com → New → Web Service
3. Set:
   - Service Type: Worker
   - Environment: Python
   - Start Command: `python main.py`
4. Add your `BOT_TOKEN` in Environment Variables

That's it! Your bot will run 24/7 on Render's free plan.
