from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime, timedelta
import calendar

app = Flask(__name__)
# my_cleanbench_secret_key_abcXYZ_123!
# 外部に公開する場合は、もっと複雑な文字列にすることをお勧めします。
app.secret_key = 'your_super_secret_key_here' 

DATABASE = 'cleanbench_reservations.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row # カラム名をキーとしてアクセスできるようにする
    return conn

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL
            )
        ''')
        db.commit()
        db.close()

# アプリケーション起動時にDB初期化
with app.app_context():
    init_db()

@app.route('/')
def index():
    today = datetime.now()
    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)

    # 予約可能な最大日付を計算（約1ヶ月先まで）
    max_bookable_date = today + timedelta(days=30) 
    
    # 該当月の予約情報を取得
    conn = get_db()
    cursor = conn.cursor()
    
    start_of_month_dt = datetime(year, month, 1)
    end_of_month_dt = (start_of_month_dt.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


    cursor.execute(
        "SELECT * FROM reservations WHERE start_time BETWEEN ? AND ? ORDER BY start_time",
        (start_of_month_dt.strftime('%Y-%m-%d 00:00'), end_of_month_dt.strftime('%Y-%m-%d 23:59'))
    )
    reservations_data = cursor.fetchall()
    conn.close()

    # 予約データを日付ごとに整理
    reservations_by_date = {}
    for res in reservations_data:
        res_date_str = res['start_time'].split(' ')[0]
        if res_date_str not in reservations_by_date:
            reservations_by_date[res_date_str] = []
        reservations_by_date[res_date_str].append(res)
    
    # カレンダーの週ごとの日付データを生成
    cal = calendar.Calendar(firstweekday=6) # 0:月曜開始, 6:日曜開始 (日本は日曜開始が多い)
    month_calendar = cal.monthdatescalendar(year, month)

    # 前月と次月の年と月を計算
    prev_month_year = year
    prev_month_month = month - 1
    if prev_month_month == 0:
        prev_month_month = 12
        prev_month_year -= 1

    next_month_year = year
    next_month_month = month + 1
    if next_month_month == 13:
        next_month_month = 1
        next_month_year += 1

    return render_template('index.html',
                           year=year,
                           month=month,
                           month_calendar=month_calendar,
                           reservations_by_date=reservations_by_date,
                           today=today,
                           prev_month_year=prev_month_year,
                           prev_month_month=prev_month_month,
                           next_month_year=next_month_year,
                           next_month_month=next_month_month,
                           max_bookable_date=max_bookable_date)

@app.route('/reserve', methods=['POST'])
def reserve():
    user_name = request.form['user_name']
    start_date_str = request.form['start_date']
    start_time_str = request.form['start_time']
    end_time_str = request.form['end_time']

    # 日時文字列をdatetimeオブジェクトに変換
    try:
        start_datetime = datetime.strptime(f"{start_date_str} {start_time_str}", '%Y-%m-%d %H:%M')
        end_datetime = datetime.strptime(f"{start_date_str} {end_time_str}", '%Y-%m-%d %H:%M')
    except ValueError:
        flash('日付または時刻の形式が不正です。', 'error')
        return redirect(url_for('index'))

    # バリデーション
    if start_datetime >= end_datetime:
        flash('終了時刻は開始時刻より後に設定してください。', 'error')
        return redirect(url_for('index'))

    if (end_datetime - start_datetime) > timedelta(days=1):
        flash('一度に予約できるのは1日以内です。', 'error')
        return redirect(url_for('index'))

    if start_datetime < datetime.now().replace(second=0, microsecond=0):
        flash('過去の日付・時刻には予約できません。', 'error')
        return redirect(url_for('index'))
    
    max_allowed_booking_date = datetime.now() + timedelta(days=30)
    if start_datetime.date() > max_allowed_booking_date.date():
        flash('1ヶ月以上先の予約はできません。', 'error')
        return redirect(url_for('index'))

    if start_datetime.minute % 15 != 0 or end_datetime.minute % 15 != 0 or \
       start_datetime.second != 0 or end_datetime.second != 0:
        flash('予約は15分単位で設定してください。', 'error')
        return redirect(url_for('index'))

    conn = get_db()
    cursor = conn.cursor()

    # 重複予約のチェック
    cursor.execute(
        """SELECT * FROM reservations WHERE
           (start_time < ? AND end_time > ?)
        """,
        (end_datetime.strftime('%Y-%m-%d %H:%M'),
         start_datetime.strftime('%Y-%m-%d %H:%M'))
    )
    existing_reservations = cursor.fetchall()
    if existing_reservations:
        flash('指定された時間帯は既に予約されています。', 'error')
        conn.close()
        return redirect(url_for('index'))

    # 予約をデータベースに保存
    cursor.execute(
        "INSERT INTO reservations (user_name, start_time, end_time) VALUES (?, ?, ?)",
        (user_name, start_datetime.strftime('%Y-%m-%d %H:%M'), end_datetime.strftime('%Y-%m-%d %H:%M'))
    )
    conn.commit()
    conn.close()
    flash('予約が完了しました！', 'success')
    return redirect(url_for('index'))

@app.route('/list')
def list_reservations():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reservations ORDER BY start_time ASC")
    reservations = cursor.fetchall()
    conn.close()
    return render_template('list.html', reservations=reservations)

@app.route('/delete/<int:reservation_id>', methods=['POST'])
def delete_reservation(reservation_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reservations WHERE id = ?", (reservation_id,))
    conn.commit()
    conn.close()
    flash('予約を削除しました。', 'success')
    return redirect(url_for('list_reservations'))

@app.route('/edit/<int:reservation_id>')
def edit_reservation(reservation_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,))
    reservation = cursor.fetchone()
    conn.close()

    if reservation is None:
        flash('指定された予約が見つかりませんでした。', 'error')
        return redirect(url_for('list_reservations'))

    start_datetime_obj = datetime.strptime(reservation['start_time'], '%Y-%m-%d %H:%M')
    end_datetime_obj = datetime.strptime(reservation['end_time'], '%Y-%m-%d %H:%M')

    today = datetime.now()
    max_bookable_date = today + timedelta(days=30) 

    return render_template('edit.html',
                           reservation=reservation,
                           start_date=start_datetime_obj.strftime('%Y-%m-%d'),
                           start_time=start_datetime_obj.strftime('%H:%M'),
                           end_time=end_datetime_obj.strftime('%H:%M'),
                           today=today,
                           max_bookable_date=max_bookable_date
                           )

@app.route('/update/<int:reservation_id>', methods=['POST'])
def update_reservation(reservation_id):
    user_name = request.form['user_name']
    start_date_str = request.form['start_date']
    start_time_str = request.form['start_time']
    end_time_str = request.form['end_time']

    try:
        start_datetime = datetime.strptime(f"{start_date_str} {start_time_str}", '%Y-%m-%d %H:%M')
        end_datetime = datetime.strptime(f"{start_date_str} {end_time_str}", '%Y-%m-%d %H:%M')
    except ValueError:
        flash('日付または時刻の形式が不正です。', 'error')
        return redirect(url_for('edit_reservation', reservation_id=reservation_id))

    if start_datetime >= end_datetime:
        flash('終了時刻は開始時刻より後に設定してください。', 'error')
        return redirect(url_for('edit_reservation', reservation_id=reservation_id))

    if (end_datetime - start_datetime) > timedelta(days=1):
        flash('一度に予約できるのは1日以内です。', 'error')
        return redirect(url_for('edit_reservation', reservation_id=reservation_id))

    if start_datetime < datetime.now().replace(second=0, microsecond=0):
        flash('過去の日付・時刻には変更できません。', 'error')
        return redirect(url_for('edit_reservation', reservation_id=reservation_id))
    
    max_allowed_booking_date = datetime.now() + timedelta(days=30)
    if start_datetime.date() > max_allowed_booking_date.date():
        flash('1ヶ月以上先の予約には変更できません。', 'error')
        return redirect(url_for('edit_reservation', reservation_id=reservation_id))

    if start_datetime.minute % 15 != 0 or end_datetime.minute % 15 != 0 or \
       start_datetime.second != 0 or end_datetime.second != 0:
        flash('予約は15分単位で設定してください。', 'error')
        return redirect(url_for('edit_reservation', reservation_id=reservation_id))

    conn = get_db()
    cursor = conn.cursor()

    # 重複予約のチェック（自分自身の予約を除く）
    cursor.execute(
        """SELECT * FROM reservations WHERE
           (start_time < ? AND end_time > ?) AND id != ?
        """,
        (end_datetime.strftime('%Y-%m-%d %H:%M'),
         start_datetime.strftime('%Y-%m-%d %H:%M'),
         reservation_id)
    )
    existing_reservations = cursor.fetchall()
    if existing_reservations:
        flash('指定された時間帯は既に予約されています。', 'error')
        conn.close()
        return redirect(url_for('edit_reservation', reservation_id=reservation_id))

    cursor.execute(
        "UPDATE reservations SET user_name = ?, start_time = ?, end_time = ? WHERE id = ?",
        (user_name, start_datetime.strftime('%Y-%m-%d %H:%M'), end_datetime.strftime('%Y-%m-%d %H:%M'), reservation_id)
    )
    conn.commit()
    conn.close()
    flash('予約を更新しました！', 'success')
    return redirect(url_for('list_reservations'))

if __name__ == '__main__':
    app.run(debug=True)