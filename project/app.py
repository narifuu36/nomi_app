from flask import Flask, render_template

app = Flask(__name__)

# トップ画面（画面A）
@app.route('/')
def index():
    # 実際はここでイベントの有無を判定して表示を切り替えます
    return render_template('index.html')

# ログイン画面（画面D）
@app.route('/login')
def login():
    return render_template('login.html')

# サインアップ（新規登録）画面（画面E）
@app.route('/signup')
def signup():
    return render_template('signup.html')

# 投票画面（画面B）
@app.route('/event')
def event():
    # 実際はここでDBからイベント情報や候補日を取得してテンプレートに渡します
    return render_template('event.html')

# 集計結果画面（画面C）
@app.route('/result')
def result():
    # 実際はここでDBから投票結果を集計してテンプレートに渡します
    return render_template('result.html')

if __name__ == '__main__':
    # debug=Trueにしておくと、コード変更時に自動でサーバーが再起動します
    app.run(debug=True, port=5000)