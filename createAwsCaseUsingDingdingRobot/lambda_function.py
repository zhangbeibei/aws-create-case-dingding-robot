import json
import time
import hmac
import base64
import hashlib
import requests
import boto3
from botocore.exceptions import ClientError

support_client = boto3.client('support', region_name='us-east-1')
secretsmanager_client = boto3.client('secretsmanager', region_name='ap-northeast-1')

secret_name = "dingding-outgoing-robot-env"


def get_secret(secret_key):
    """
    获取 aws secrects manager 中的值
    """
    try:
        get_secret_value_response = secretsmanager_client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        raise e
    else:
        if 'SecretString' in get_secret_value_response:
            secrets = json.loads(get_secret_value_response['SecretString'])
            secret_value = secrets[secret_key]
            return secret_value
        else:
            decoded_binary_secret = base64.b64decode(get_secret_value_response['SecretBinary'])


def calcu_legal_timestamp_sign(request_timestamp):
    """
    计算合法的时间戳和签名
    """
    app_secret = get_secret('app_secret').strip()
    timestamp = str(round(time.time() * 1000))
    app_secret_enc = app_secret.encode('utf-8')
    string_to_sign = '{}\n{}'.format(request_timestamp, app_secret)
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(app_secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(hmac_code).decode('utf-8')
    return timestamp, sign


def selectMes(request_message):
    """
    根据输入内容进行不同action以及选择不同返回信息
    """
    send_message = 'AWS-[欢迎使用自动创建AWS工单钉钉机器人服务，本机器人目前支持3个功能。请注意换行以及英文逗号]\n\n' + \
                   '[功能1：搜索AWS服务的serviceCode和categoryCode。请按以下格式输入]\n查找ServiceCode:{AWS服务名称，支持简写}\n\n' + \
                   '[功能2：创建 AWS case。请按以下格式输入]\n提工单\nsubject:{case 主题}\nbody:{case 描述}\n' + \
                   'severityCode:{low|normal|high|urgent|critical}\nserviceCode:{aws serviceCode}\ncategoryCode:{aws service categoryCode}\n\n' + \
                   '[功能3：释放 AWS case。请按以下格式输入]\n释放case，case_id:{case_id}'

    case_message_dict = get_valid_dict(request_message)
    if case_message_dict is not None:
        send_message = create_aws_case(case_message_dict)
    elif '查找servicecode' in request_message.lower():
        service_name = request_message.split(':')[1]
        send_message = get_aws_serviceCode_categoryCode(service_name)
    elif '释放' in request_message.lower():
        send_message = resolve_aws_case(request_message)
    return sendText(send_message)


def get_valid_dict(request_message):
    """
    判断输入的创建case格式是否正确并转换成dict格式
    """
    correct_key_list = ['subject', 'body', 'serviceCode', 'categoryCode', 'severityCode']
    if len(request_message.split('\n')) == 6:
        case_message_dict = {}
        for message in request_message.split('\n')[1:]:
            case_message_dict[message.split(':')[0]] = message.split(':')[1]
        if set(case_message_dict.keys()) == set(correct_key_list):
            return case_message_dict


def create_aws_case(case_message_dict):
    """
    创建aws技术case
    """
    subject = case_message_dict['subject']
    communicationBody = case_message_dict['body']
    serviceCode = case_message_dict['serviceCode']
    categoryCode = case_message_dict['categoryCode']
    severityCode = case_message_dict['severityCode']
    try:
        response = support_client.create_case(
            subject=subject,
            serviceCode=serviceCode,
            categoryCode=categoryCode,
            severityCode=severityCode,
            communicationBody=communicationBody,
            # ccEmailAddresses = [
            #         "abc@test.com",
            # ],
            language="en",
            issueType="technical"
        )
        case_id = response["caseId"]
    except:
        return "AWS-[创建工单失败]\n请输入正确的格式以及正确的 serviceCode 和 categoryCode"
    else:
        return 'AWS-[创建工单成功]\ncase id: ' + case_id


def resolve_aws_case(request_message):
    """
    释放 aws case
    """
    try:
        case_id = request_message.split(':')[1]
        support_client.resolve_case(caseId=case_id)
    except:
        return 'AWS-[释放case失败]\ncase_id:' + case_id + '不存在'
    else:
        return 'AWS-[释放case成功]\ncase_id:' + case_id + '已释放'


def get_aws_serviceCode_categoryCode(service_name):
    """
    根据服务名获取获取 aws servicecode 和 categorycode
    """
    response = support_client.describe_services()
    for service in response["services"]:
        if service['name'].lower().find(service_name.lower()) != -1:
            return 'AWS-[serviceCode和categoryCode信息如下]\n' + str(service)
    return 'AWS-[请输入正确的 AWS Service 名称]'


def sendText(send_message):
    """
    定义发送钉钉文本消息格式
    """
    message = {
        "msgtype": "text",
        "text": {
            "content": send_message
        },
        "at": {
            "isAtAll": False
        }
    }
    return message


def lambda_handler(event, context):
    # 获取请求中信息
    request_timestamp = event['headers']['timestamp'].strip()
    request_sign = event['headers']['sign'].strip()
    request_message = json.loads(event['body'])['text']['content'].strip()

    # 计算合法的时间戳和签名
    timestamp, sign = calcu_legal_timestamp_sign(request_timestamp)
    print(timestamp, sign)
    # 判断请求是否合法
    if abs(int(request_timestamp) - int(timestamp)) < 3600000 and request_sign == sign:
        header = {
            "Content-Type": "application/json",
            "Charset": "UTF-8"
        }
        # 拼接发送钉钉消息的webhook
        access_token = get_secret('access_token').strip()
        webhook = "https://oapi.dingtalk.com/robot/send?access_token=" + access_token + "&timestamp=" + timestamp + "&sign=" + sign
        # 发送消息
        message_json = json.dumps(selectMes(request_message))
        # 返回发送状态
        info = requests.post(url=webhook, data=message_json, headers=header)
        print(info.text)
    else:
        print("Warning: Not DingDing's legal post request")