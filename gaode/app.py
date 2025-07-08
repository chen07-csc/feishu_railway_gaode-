import os
import json
import httpx
import logging
import asyncio
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from typing import Optional, Dict, AsyncGenerator
from datetime import datetime
from dotenv import load_dotenv
import uuid

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

app = FastAPI()

# Dify API配置
DIFY_API_KEY = os.getenv("DIFY_API_KEY")
DIFY_API_ENDPOINT = os.getenv("DIFY_API_ENDPOINT")

# 飞书配置
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")

# 会话存储
conversation_store: Dict[str, Dict] = {}

async def get_feishu_access_token():
    """获取飞书访问令牌"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {
        "Content-Type": "application/json"
    }
    data = {
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
            token_data = response.json()
            logger.info(f"获取飞书访问令牌响应: {token_data}")
            return token_data.get("tenant_access_token")
    except Exception as e:
        logger.error(f"获取飞书访问令牌错误: {str(e)}")
        raise

async def call_dify_api(message: str, user_id: str, conversation_id: Optional[str] = None) -> AsyncGenerator[Dict, None]:
    """调用Dify API并返回流式响应"""
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # 构建请求数据，包含MCP所需的参数
    data = {
        "inputs": {
            "message": message,  # 用户输入消息
            "session_id": conversation_id or str(uuid.uuid4()),  # 使用conversation_id作为session_id
            "stream": True  # 启用流式输出
        },
        "query": message,
        "user": user_id,
        "response_mode": "streaming",
        "conversation_id": conversation_id
    }
    
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream('POST', 
                                   f"{DIFY_API_ENDPOINT}/chat-messages",
                                   headers=headers,
                                   json=data,
                                   timeout=30.0) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            event_data = json.loads(line[6:])
                            # 处理MCP特定的响应格式
                            if "error" in event_data:
                                logger.error(f"MCP API错误: {event_data['error']}")
                                yield {"event": "error", "message": f"MCP API错误: {event_data['error']}"}
                            else:
                                yield event_data
                        except json.JSONDecodeError as e:
                            logger.error(f"JSON解析错误: {e}")
                            continue
    except Exception as e:
        logger.error(f"调用Dify API错误: {str(e)}")
        yield {"event": "error", "message": str(e)}

async def send_feishu_message(access_token: str, receive_id: str, content: str, msg_type: str = "text"):
    """发送飞书消息"""
    # 自动判断类型
    if receive_id.startswith("oc_"):
        receive_id_type = "chat_id"
    elif receive_id.startswith("ou_"):
        receive_id_type = "open_id"
    else:
        logger.warning(f"未知 receive_id 类型: {receive_id}")
        receive_id_type = "chat_id"  # 默认使用群聊

    # URL中添加receive_id_type作为查询参数
    url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # 从请求体中移除receive_id_type
    data = {
        "receive_id": receive_id,
        "msg_type": msg_type,
        "content": json.dumps({"text": content}, ensure_ascii=False)
    }

    try:
        logger.info(f"发送飞书消息 headers: {headers}")
        logger.info(f"发送飞书消息 URL: {url}")
        logger.info(f"发送飞书消息 data: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                json=data,
                timeout=30.0
            )
            logger.info(f"飞书API响应状态码: {response.status_code}")
            logger.info(f"飞书API响应内容: {response.text}")
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"发送飞书消息错误: {str(e)}")
        logger.error(f"请求数据: {data}")
        if isinstance(e, httpx.HTTPError) and hasattr(e, 'response'):
            logger.error(f"响应状态码: {e.response.status_code}")
            logger.error(f"响应内容: {e.response.text}")
        raise

async def process_ai_response(message: str, user_id: str, conversation_id: Optional[str] = None):
    """处理AI响应"""
    accumulated_response = ""
    try:
        access_token = await get_feishu_access_token()
        
        async for event_data in call_dify_api(message, user_id, conversation_id):
            event_type = event_data.get("event")
            
            if event_type == "message":
                answer_chunk = event_data.get("answer", "")
                accumulated_response += answer_chunk
                
                if len(accumulated_response) >= 50:
                    try:
                        await send_feishu_message(access_token, user_id, accumulated_response)
                        accumulated_response = ""
                    except Exception as e:
                        logger.error(f"发送消息块错误: {str(e)}")
                    
            elif event_type == "message_end":
                if accumulated_response:
                    try:
                        await send_feishu_message(access_token, user_id, accumulated_response)
                    except Exception as e:
                        logger.error(f"发送最终消息错误: {str(e)}")
                
                new_conversation_id = event_data.get("conversation_id")
                if new_conversation_id:
                    conversation_store[user_id] = {
                        "conversation_id": new_conversation_id,
                        "updated_at": datetime.now()
                    }
                    
            elif event_type == "error":
                error_message = event_data.get("message", "未知错误")
                logger.error(f"AI响应错误: {error_message}")
                try:
                    await send_feishu_message(access_token, user_id, f"处理您的请求时遇到错误: {error_message}")
                except Exception as e:
                    logger.error(f"发送错误消息失败: {str(e)}")
    except Exception as e:
        logger.error(f"处理AI响应过程中发生错误: {str(e)}")
        try:
            await send_feishu_message(access_token, user_id, f"系统错误: {str(e)}")
        except Exception as send_error:
            logger.error(f"发送系统错误消息失败: {str(send_error)}")

@app.get("/")
async def root():
    """健康检查接口"""
    return {"status": "ok"}

@app.post("/feishu/webhook")
async def feishu_webhook(request: Request):
    """处理飞书webhook请求"""
    logger.info("收到webhook请求")
    try:
        body = await request.body()
        body_str = body.decode('utf-8')
        data = json.loads(body_str)
        
        # 处理飞书的验证请求
        if "challenge" in data:
            return Response(
                content=json.dumps({
                    "challenge": data["challenge"],
                    "code": 0
                }),
                media_type="application/json"
            )
            
        # 处理消息事件
        if "event" in data:
            event = data.get("event", {})
            message = event.get("message", {})
            if message.get("message_type") == "text":
                # 解析消息内容
                message_content = message.get("content", "{}")
                content_json = json.loads(message_content)
                text = content_json.get("text", "")
                
                # 获取发送者ID
                sender_id = event.get("sender", {}).get("sender_id", {}).get("open_id")
                chat_id = message.get("chat_id")
                receive_id = chat_id if chat_id else sender_id
                
                if receive_id:
                    # 获取现有会话ID
                    conversation_data = conversation_store.get(receive_id, {})
                    conversation_id = conversation_data.get("conversation_id")
                    
                    # 异步处理AI响应
                    asyncio.create_task(process_ai_response(text, receive_id, conversation_id))
                    
        return Response(
            content=json.dumps({"code": 0, "msg": "success"}),
            media_type="application/json"
        )
        
    except Exception as e:
        logger.error(f"处理webhook错误: {str(e)}")
        return Response(
            content=json.dumps({"code": 0, "msg": "success"}),
            media_type="application/json"
        )

if __name__ == "__main__":
    import uvicorn
    logger.info("启动服务器...")
    uvicorn.run(app, host="0.0.0.0", port=8000) 
