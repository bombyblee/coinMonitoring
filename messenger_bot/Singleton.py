class Singleton(type):
    # 클래스의 인스턴스를 저장할 속성
    __instances = {}

    def __call__(cls, *args, **kwargs):
        """
        클래스로 인스턴스를 만들 때 호출되는 메서드
        :param args:
        :param kwargs:
        :return:
        """
        # 클래스로 인스턴스를 생성하지 않았는지 확인
        if cls not in cls.__instances:
            # 생성하지 않았으면 인스턴스를 생성하여 속성에 저장
            cls.__instances[cls] = super().__call__(*args, **kwargs)
        # 클래스로 인스턴스를 생성했으면 인스턴스 반환
        return cls.__instances[cls]