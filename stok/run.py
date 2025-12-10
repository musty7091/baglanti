from app import create_app

app = create_app()

if __name__ == '__main__':
    # host='0.0.0.0' ekledik, böylece ağdaki diğer cihazlar seni görebilir.
    app.run(debug=True, host='0.0.0.0')