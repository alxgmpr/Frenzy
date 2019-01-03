from worker import *


def main():
    print('<<< Frenzy Monitor - Alexander Gompper 2018 >>>')
    try:
        with open('config.json') as config_file:
            config = json.load(config_file)
    except IOError:
        print('[error] couldnt load config file')
        return False
    w = Worker(configuration=config)
    w.start()


if __name__ == '__main__':
    main()
