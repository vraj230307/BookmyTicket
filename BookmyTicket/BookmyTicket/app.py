from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import time
import qrcode
import base64
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'super_secret_key_bookmyticket'
DB_NAME = 'bookmyticket.db'

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                failed_attempts INTEGER DEFAULT 0,
                is_blocked INTEGER DEFAULT 0,
                blocked_until REAL DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                date TEXT NOT NULL,
                status TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                event_id INTEGER,
                timestamp REAL,
                num_seats INTEGER,
                selected_seats TEXT,
                FOREIGN KEY(user_id) REFERENCES Users(id),
                FOREIGN KEY(event_id) REFERENCES Events(id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                event_id INTEGER,
                content TEXT,
                FOREIGN KEY(user_id) REFERENCES Users(id),
                FOREIGN KEY(event_id) REFERENCES Events(id)
            )
        ''')
        
        # Insert mock data if empty
        cursor.execute("SELECT COUNT(*) FROM Events")
        if cursor.fetchone()[0] == 0:
            events = [
                ('Arijit Singh Live', 'Concert', '2026-04-15', 'Upcoming'),
                ('Jawan', 'Movie', '2026-03-25', 'Upcoming'),
                ('India vs Pakistan - World Cup', 'Sports', '2026-04-10', 'Upcoming'),
                ('IPL Final', 'Sports', '2026-05-29', 'Upcoming'),
                ('Diljit Dosanjh Concert', 'Concert', '2026-06-12', 'Upcoming'),
                ('Pathaan', 'Movie', '2025-12-10', 'Ended')
            ]
            cursor.executemany("INSERT INTO Events (name, type, date, status) VALUES (?, ?, ?, ?)", events)
        conn.commit()

init_db()

@app.before_request
def check_block():
    if 'user_id' in session:
        with get_db() as conn:
            user = conn.cursor().execute("SELECT is_blocked, blocked_until FROM Users WHERE id = ?", (session['user_id'],)).fetchone()
            if user and user['is_blocked'] == 1:
                if time.time() < user['blocked_until']:
                    flash("Your account is temporarily blocked for 7 days due to suspicious activity.", "error")
                    session.clear()
                    return redirect(url_for('login'))
                else:
                    # Unblock if 7 days passed
                    conn.cursor().execute("UPDATE Users SET is_blocked = 0, failed_attempts = 0, blocked_until = 0 WHERE id = ?", (session['user_id'],))
                    conn.commit()

@app.route('/')
def index():
    with get_db() as conn:
        events = conn.cursor().execute("SELECT * FROM Events").fetchall()
    return render_template('index.html', events=events)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        with get_db() as conn:
            cursor = conn.cursor()
            user = cursor.execute("SELECT * FROM Users WHERE email = ?", (email,)).fetchone()
            if user and user['password'] == password:
                if user['is_blocked'] == 1:
                    if time.time() < user['blocked_until']:
                        flash("Your account is temporarily blocked for 7 days due to suspicious activity.", "error")
                        return render_template('login.html')
                    else:
                        # Unblock if 7 days passed
                        cursor.execute("UPDATE Users SET is_blocked = 0, failed_attempts = 0, blocked_until = 0 WHERE id = ?", (user['id'],))
                        conn.commit()
                        
                session['user_id'] = user['id']
                session['user_name'] = user['name']
                return redirect(url_for('index'))
            else:
                flash('Invalid credentials', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        with get_db() as conn:
            try:
                conn.cursor().execute("INSERT INTO Users (name, email, password) VALUES (?, ?, ?)", (name, email, password))
                conn.commit()
                flash("Registration successful. Please login.", "success")
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                flash("Email already exists", "error")
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    with get_db() as conn:
        cursor = conn.cursor()
        query = """
            SELECT b.id, b.timestamp, b.num_seats, b.selected_seats, 
                   e.name as event_name, e.date as event_date, e.status as event_status
            FROM Bookings b
            JOIN Events e ON b.event_id = e.id
            WHERE b.user_id = ?
            ORDER BY b.timestamp DESC
        """
        rows = cursor.execute(query, (session['user_id'],)).fetchall()
        
        bookings = []
        for row in rows:
            booking = dict(row)
            qr_data = f"Booking ID: TKT-{booking['id']:05d}\nEvent: {booking['event_name']}\nSeats: {booking['selected_seats']}\nUser: {session.get('user_name', '')}"
            
            qr = qrcode.QRCode(version=1, box_size=5, border=2)
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            buffered = BytesIO()
            img.save(buffered, format="PNG")
            booking['qr_base64'] = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            bookings.append(booking)
            
    return render_template('profile.html', bookings=bookings)

@app.route('/book/<int:event_id>', methods=['GET', 'POST'])
def book(event_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    with get_db() as conn:
        cursor = conn.cursor()
        event = cursor.execute("SELECT * FROM Events WHERE id = ?", (event_id,)).fetchone()
        
        if not event or event['status'] != 'Upcoming':
            flash("You can only book tickets for upcoming events.", "error")
            return redirect(url_for('index'))

        if request.method == 'POST':
            # BOT DETECTION LOGIC: Time-to-Action
            start_time = float(request.form.get('start_time', time.time()))
            time_taken = time.time() - start_time
            
            if time_taken < 3.0:
                user_id = session['user_id']
                cursor.execute("UPDATE Users SET failed_attempts = failed_attempts + 1 WHERE id = ?", (user_id,))
                conn.commit()
                
                user = cursor.execute("SELECT failed_attempts FROM Users WHERE id = ?", (user_id,)).fetchone()
                
                # Check for 3 attempt block
                if user['failed_attempts'] >= 3:
                    block_duration = 7 * 24 * 60 * 60 # 7 days
                    blocked_until = time.time() + block_duration
                    cursor.execute("UPDATE Users SET is_blocked = 1, blocked_until = ? WHERE id = ?", (blocked_until, user_id))
                    conn.commit()
                    session.clear()
                    flash("Account blocked for 7 days due to suspicious bot activity.", "error")
                    return redirect(url_for('login'))
                
                flash(f"Bot Detected: Form submitted too quickly ({time_taken:.1f}s). Attempt recorded.", "error")
                # Intentionally resetting the start_time on re-render to force them to wait
                return render_template('booking.html', event=event, start_time=time.time())
            
            # Successful booking
            num_seats = request.form.get('num_seats', type=int)
            selected_seats = request.form.get('selected_seats', '')
            total_price = request.form.get('total_price', type=float, default=0.0)
            
            if not num_seats or num_seats < 1 or num_seats > 8:
                flash("You must select between 1 and 8 seats.", "error")
                return render_template('booking.html', event=event, start_time=time.time())
                
            if not selected_seats:
                flash("Please select your seats.", "error")
                return render_template('booking.html', event=event, start_time=time.time())

            # Store pending details in session before payment
            session['pending_booking'] = {
                'event_id': event_id,
                'num_seats': num_seats,
                'selected_seats': selected_seats,
                'total_price': total_price,
                'event_name': event['name']
            }
            return redirect(url_for('payment'))
            
    return render_template('booking.html', event=event, start_time=time.time())

@app.route('/payment', methods=['GET', 'POST'])
def payment():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    pending = session.get('pending_booking')
    if not pending:
        flash("No active booking found.", "error")
        return redirect(url_for('index'))
        
    total_amount = pending.get('total_price', pending['num_seats'] * 500)
    
    if request.method == 'POST':
        # Payment Simulated Success -> Complete Booking
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO Bookings (user_id, event_id, timestamp, num_seats, selected_seats) VALUES (?, ?, ?, ?, ?)", 
                           (session['user_id'], pending['event_id'], time.time(), pending['num_seats'], pending['selected_seats']))
            
            # Reset failed attempts just in case
            cursor.execute("UPDATE Users SET failed_attempts = 0 WHERE id = ?", (session['user_id'],))
            conn.commit()
            
        flash(f"Payment successful! Booked {pending['num_seats']} ticket(s) for {pending['event_name']}.", "success")
        session.pop('pending_booking', None)
        return redirect(url_for('profile'))
        
    # GET Request -> Generate QR Code
    upi_string = f"upi://pay?pa=bookmyticket@upi&pn=BookMyTicket&am={total_amount}&cu=INR"
    
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(upi_string)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
    
    return render_template('payment.html', pending=pending, total_amount=total_amount, qr_base64=qr_base64)

@app.route('/feedback/<int:event_id>', methods=['GET', 'POST'])
def feedback(event_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    with get_db() as conn:
        cursor = conn.cursor()
        event = cursor.execute("SELECT * FROM Events WHERE id = ?", (event_id,)).fetchone()
        
        if not event or event['status'] != 'Ended':
            flash("You can only leave feedback for ended events.", "error")
            return redirect(url_for('index'))
            
        if request.method == 'POST':
            content = request.form['content']
            cursor.execute("INSERT INTO Feedback (user_id, event_id, content) VALUES (?, ?, ?)", (session['user_id'], event_id, content))
            conn.commit()
            flash("Feedback submitted successfully!", "success")
            return redirect(url_for('index'))
            
    return render_template('feedback.html', event=event)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if session.get('is_admin'):
        with get_db() as conn:
            users = conn.cursor().execute("SELECT * FROM Users").fetchall()
        return render_template('admin.html', users=users)
        
    if request.method == 'POST':
        password = request.form.get('admin_password')
        if password == 'admin123': # Secret password for the admin
            session['is_admin'] = True
            return redirect(url_for('admin'))
        else:
            flash('Invalid admin password', 'error')
            
    return render_template('admin.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
