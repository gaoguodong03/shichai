[
  {
    "task_id": 1,
    "pre_code": "def before_task(memory_bus,logger,process_control):\n    return",
    "tool_id": 1,
    "parameters": [],
    "post_code": "def after_task(memory_bus,logger,process_control):\n    result = [{\"type\":\"text\",\"data\":\"\"\"🌟 欢迎使用学伴研讨！ 🌟<BR>\n我们将通过以下方式助力您的思维碰撞：<BR>\n✅ AI导师为您定制研讨主题<BR>\n✅ 虚拟学伴参与多角度讨论<BR>\n✅ 智能助教提供专业引导<BR>\n✅ 个性化学术评价助力成长<BR>\n\"\"\"}]\n    return result",
    "task": "展示欢迎词"
  },
  {
    "task_id": 2,
    "pre_code": "def before_task(memory_bus,logger,process_control):\n    return",
    "tool_id": 41,
    "parameters": [
      {
        "name": "var01",
        "sourceType": "input",
        "sourceData": {
          "type": "editBox",
          "option": {
            "variableName": "researchDirection",
            "prompt": "请输入一个研讨方向",
            "defaultValue": "",
            "inputMode": "singleLine"
          }
        }
      },
      {
        "name": "var02",
        "sourceType": "const",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": "0"
          }
        }
      },
      {
        "name": "var03",
        "sourceType": "const",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": "0"
          }
        }
      },
      {
        "name": "var04",
        "sourceType": "const",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": "0"
          }
        }
      }
    ],
    "post_code": "def after_task(memory_bus,logger,process_control):\n    # 敏感词检测函数开始\n    def detectSensitiveWords(sentence):\n        sensitive_word_sentence_list = [\"腐败中国\",\"三个呆婊\",\"你办事我放心\",\"社会主义灭亡\",\"打倒中国\",\"共产党\",\"共产主义\",\"胡锦涛\",\"江泽民\",\"江主席\",\"李鹏\",\"罗干\",\"温家宝\",\"打倒中共\",\"习近平\",\"习主席\",\"朱镕基\",\"抵制中共\",\"灭亡中国\",\"亡党亡国\",\"粉碎四人帮\",\"激流中国\",\"特供\",\"特贡\",\"特共\",\"zf大楼\",\"殃视\",\"贪污腐败\",\"强制拆除\",\"形式主义\",\"政治风波\",\"太子党\",\"上海帮\",\"北京帮\",\"清华帮\",\"红色贵族\",\"权贵集团\",\"河蟹社会\",\"喝血社会\",\"九风\",\"9风\",\"十七大\",\"十7大\",\"17da\",\"九学\",\"9学\",\"四风\",\"4风\",\"双规\",\"南街村\",\"最淫官员\",\"警匪\",\"官匪\",\"独夫民贼\",\"官商勾结\",\"城管暴力执法\",\"强制捐款\",\"毒豺\",\"一党执政\",\"一党专制\",\"一党专政\",\"专制政权\",\"宪法法院\",\"胡平\",\"苏晓康\",\"贺卫方\",\"谭作人\",\"焦国标\",\"万润南\",\"张志新\",\"辛灝年\",\"高勤荣\",\"王炳章\",\"高智晟\",\"司马璐\",\"刘晓竹\",\"刘宾雁\",\"魏京生\",\"寻找林昭的灵魂\",\"别梦成灰\",\"谁是新中国\",\"讨伐中宣部\",\"异议人士\",\"民运人士\",\"启蒙派\",\"选国家主席\",\"民一主\",\"min主\",\"民竹\",\"民珠\",\"民猪\",\"chinesedemocracy\",\"大赦国际\",\"国际特赦\",\"da选\",\"投公\",\"公头\",\"宪政\",\"平反\",\"党章\",\"维权\",\"昝爱宗\",\"宪章\",\"08宪\",\"08xz\",\"抿主\",\"敏主\",\"人拳\",\"人木又\",\"人quan\",\"renquan\",\"中国人权\",\"中国新民党\",\"群体事件\",\"群体性事件\",\"上中央\",\"去中央\",\"讨说法\",\"请愿\",\"请命\",\"公开信\",\"联名上书\",\"万人大签名\",\"万人骚动\",\"截访\",\"上访\",\"shangfang\",\"信访\",\"访民\",\"集合\",\"集会\",\"组织集体\",\"静坐\",\"静zuo\",\"jing坐\",\"示威\",\"示wei\",\"游行\",\"you行\",\"油行\",\"游xing\",\"youxing\",\"官逼民反\",\"反party\",\"反共\",\"抗议\",\"亢议\",\"抵制\",\"低制\",\"底制\",\"di制\",\"抵zhi\",\"dizhi\",\"boycott\",\"血书\",\"焚烧中国国旗\",\"baoluan\",\"流血冲突\",\"出现暴动\",\"发生暴动\",\"引起暴动\",\"baodong\",\"灭共\",\"杀毙\",\"罢工\",\"霸工\",\"罢考\",\"罢餐\",\"霸餐\",\"罢参\",\"罢饭\",\"罢吃\",\"罢食\",\"罢课\",\"罢ke\",\"霸课\",\"ba课\",\"罢教\",\"罢学\",\"罢运\",\"网特\",\"网评员\",\"网络评论员\",\"五毛党\",\"五毛们\",\"5毛党\",\"戒严\",\"jieyan\",\"jie严\",\"戒yan\",\"8的平方事件\",\"知道64\",\"八九年\",\"贰拾年\",\"2o年\",\"20和谐年\",\"贰拾周年\",\"六四\",\"六河蟹四\",\"六百度四\",\"六和谐四\",\"陆四\",\"陆肆\",\"198964\",\"5月35\",\"89年春夏之交\",\"64惨案\",\"64时期\",\"64运动\",\"4事件\",\"四事件\",\"北京风波\",\"学潮\",\"学chao\",\"xuechao\",\"学百度潮\",\"门安天\",\"天按门\",\"坦克压大学生\",\"民主女神\",\"历史的伤口\",\"高自联\",\"北高联\",\"血洗京城\",\"四二六社论\",\"王丹\",\"柴玲\",\"沈彤\",\"封从德\",\"王超华\",\"王维林\",\"吾尔开希\",\"吾尔开西\",\"侯德健\",\"阎明复\",\"方励之\",\"蒋捷连\",\"丁子霖\",\"辛灏年\",\"蒋彦永\",\"严家其\",\"陈一咨\",\"中华局域网\",\"党的喉舌\",\"互联网审查\",\"当局严密封锁\",\"新闻封锁\",\"封锁消息\",\"爱国者同盟\",\"关闭所有论坛\",\"网络封锁\",\"金盾工程\",\"gfw\",\"无界浏览\",\"无界网络\",\"自由门\",\"何清涟\",\"中国的陷阱\",\"汪兆钧\",\"记者无疆界\",\"境外媒体\",\"维基百科\",\"纽约时报\",\"bbc中文网\",\"华盛顿邮报\",\"世界日报\",\"东森新闻网\",\"东森电视\",\"星岛日报\",\"wikipedia\",\"youtube\",\"googleblogger\",\"美国广播公司\",\"英国金融时报\",\"自由亚洲\",\"自由时报\",\"中国时报\",\"反分裂\",\"威胁论\",\"左翼联盟\",\"钓鱼岛\",\"保钓组织\",\"主权\",\"弓单\",\"火乍\",\"木仓\",\"石肖\",\"核蛋\",\"步qiang\",\"bao炸\",\"爆zha\",\"baozha\",\"zha药\",\"zha弹\",\"炸dan\",\"炸yao\",\"zhadan\",\"zhayao\",\"hmtd\",\"三硝基甲苯\",\"六氟化铀\",\"炸药配方\",\"弹药配方\",\"炸弹配方\",\"皮箱炸弹\",\"火药配方\",\"人体炸弹\",\"人肉炸弹\",\"解放军\",\"兵力部署\",\"军转\",\"军事社\",\"8341部队\",\"第21集团军\",\"七大军区\",\"7大军区\",\"北京军区\",\"沈阳军区\",\"济南军区\",\"成都军区\",\"广州军区\",\"南京军区\",\"兰州军区\",\"颜色革命\",\"规模冲突\",\"塔利班\",\"基地组织\",\"恐怖分子\",\"恐怖份子\",\"三股势力\",\"印尼屠华\",\"印尼事件\",\"蒋公纪念歌\",\"马英九\",\"mayingjiu\",\"李天羽\",\"苏贞昌\",\"林文漪\",\"陈水扁\",\"陈s扁\",\"陈随便\",\"阿扁\",\"a扁\",\"告全国同胞书\",\"台百度湾\",\"台完\",\"台wan\",\"taiwan\",\"台弯\",\"湾台\",\"台湾国\",\"台湾共和国\",\"台军\",\"台独\",\"台毒\",\"台du\",\"taidu\",\"twdl\",\"一中一台\",\"打台湾\",\"两岸战争\",\"攻占台湾\",\"支持台湾\",\"进攻台湾\",\"占领台湾\",\"统一台湾\",\"收复台湾\",\"登陆台湾\",\"解放台湾\",\"解放tw\",\"解决台湾\",\"光复民国\",\"台湾独立\",\"台湾问题\",\"台海问题\",\"台海危机\",\"台海统一\",\"台海大战\",\"台海战争\",\"台海局势\",\"入联\",\"入耳关\",\"中华联邦\",\"国民党\",\"x民党\",\"民进党\",\"青天白日\",\"闹独立\",\"duli\",\"fenlie\",\"日本万岁\",\"小泽一郎\",\"劣等民族\",\"汉人\",\"汉维\",\"维汉\",\"维吾\",\"吾尔\",\"热比娅\",\"伊力哈木\",\"疆独\",\"东突厥斯坦解放组织\",\"东突解放组织\",\"蒙古分裂分子\",\"列确\",\"阿旺晋美\",\"藏人\",\"臧人\",\"zang人\",\"藏民\",\"藏m\",\"达赖\",\"赖达\",\"dalai\",\"哒赖\",\"dl喇嘛\",\"丹增嘉措\",\"打砸抢\",\"西独\",\"藏独\",\"葬独\",\"臧独\",\"藏毒\",\"藏du\",\"zangdu\",\"支持zd\",\"藏暴乱\",\"藏青会\",\"雪山狮子旗\",\"拉萨\",\"啦萨\",\"啦沙\",\"啦撒\",\"拉sa\",\"lasa\",\"la萨\",\"西藏\",\"藏西\",\"藏春阁\",\"藏獨\",\"藏独\",\"藏独立\",\"藏妇会\",\"藏青会\",\"藏字石\",\"xizang\",\"xi藏\",\"x藏\",\"西z\",\"tibet\",\"希葬\",\"希藏\",\"硒藏\",\"稀藏\",\"西脏\",\"西奘\",\"西葬\",\"西臧\",\"援藏\",\"bjork\",\"王千源\",\"安拉\",\"回教\",\"回族\",\"回回\",\"回民\",\"穆斯林\",\"穆罕穆德\",\"穆罕默德\",\"默罕默德\",\"伊斯兰\",\"圣战组织\",\"清真\",\"清zhen\",\"qingzhen\",\"真主\",\"阿拉伯\",\"高丽棒子\",\"韩国狗\",\"满洲第三帝国\",\"满狗\",\"鞑子\",\"江丑闻\",\"江嫡系\",\"江毒\",\"江独裁\",\"江蛤蟆\",\"江核心\",\"江黑心\",\"江胡内斗\",\"江祸心\",\"江家帮\",\"江绵恒\",\"江派和胡派\",\"江派人马\",\"江泉集团\",\"江人马\",\"江三条腿\",\"江氏集团\",\"江氏家族\",\"江氏政治局\",\"江氏政治委员\",\"江梳头\",\"江太上\",\"江戏子\",\"江系人\",\"江系人马\",\"江宰民\",\"江贼\",\"江贼民\",\"麻果丸\",\"麻将透\",\"麻醉弹\",\"麻醉狗\",\"麻醉枪\",\"麻醉槍\",\"麻醉药\",\"麻醉藥\",\"台独\",\"台湾版假币\",\"台湾独立\",\"台湾国\",\"台湾应该独立\",\"台湾有权独立\",\"天灭中共\",\"中共帮凶\",\"中共保命\",\"中共裁\",\"中共党文化\",\"中共腐败\",\"中共的血旗\",\"中共的罪恶\",\"中共帝国\",\"中共独裁\",\"中共封锁\",\"中共封网\",\"中共腐败\",\"中共黑\",\"中共黑帮\",\"中共解体\",\"中共近期权力斗争\",\"中共恐惧\",\"中共权力斗争\",\"中共任用\",\"中共退党\",\"中共洗脑\",\"中共邪教\",\"中共政治游戏\",\"中共邪毒素\"]\n        # 遍历敏感词列表，检查是否在句子中\n        for word in sensitive_word_sentence_list:\n            if word in sentence:\n                return True\n        return False\n    # 敏感词检测函数结束\n    researchDirection = memory_bus.get(\"inputVar\")['researchDirection']\n    sensitive = detectSensitiveWords(researchDirection)\n    if sensitive == True:\n        memory_bus.add(\"sensitive\",\"True\")\n        result = [{\"type\":\"text\",\"data\":\"抱歉，我无法回复你的问题！\"}]\n        return result\n    else:\n        memory_bus.add(\"sensitive\",\"False\")\n        prompt = f\"\"\"请给出一个有关{researchDirection}的研讨主题，主题长度控制在8-20字，不要输出多余的内容\"\"\"\n        memory_bus.add(\"getTopicPrompt\",prompt)\n        return",
    "task": "学生输入研讨方向"
  },
  {
    "task_id": 3,
    "pre_code": "def before_task(memory_bus,logger,process_control):\n    sensitive = memory_bus.get(\"sensitive\")\n    if sensitive == \"True\":\n        process_control.abort_process()\n        return\n    else:\n        return",
    "tool_id": 10019,
    "parameters": [
      {
        "name": "content",
        "sourceType": "refer",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": "codeVar.getTopicPrompt"
          }
        }
      }
    ],
    "post_code": "def after_task(memory_bus,logger,process_control):\n    llmRepy = memory_bus.get(\"thisTask\")[\"choices\"][0][\"message\"][\"content\"]\n    memory_bus.add(\"topic\",llmRepy)\n    result = [{\"type\":\"text\",\"data\":\"老师提出的研讨主题：\"+llmRepy}]\n    memory_bus.add(\"studentView\",\"\")\n    memory_bus.add(\"dialog\",[{\"role\": \"teacher\", \"value\":llmRepy}])\n    memory_bus.add(\"schoolmatePrompt\",\"\")\n    memory_bus.add(\"assistantPrompt\",\"\")\n    memory_bus.add(\"assistant\",0)\n    return result",
    "task": "大模型根据课程内容提出研讨主题"
  },
  {
    "task_id": 4,
    "pre_code": "def before_task(memory_bus,logger,process_control):\n    return",
    "tool_id": 41,
    "parameters": [
      {
        "name": "var01",
        "sourceType": "input",
        "sourceData": {
          "type": "singleSelect",
          "option": {
            "variableName": "isContinue",
            "prompt": "请选择是否继续发言",
            "defaultValue": "1",
            "options": [
              {
                "name": "离开研讨",
                "value": "0"
              },
              {
                "name": "提出自己的看法或问题",
                "value": "1"
              }
            ]
          }
        }
      },
      {
        "name": "var02",
        "sourceType": "input",
        "sourceData": {
          "type": "editBox",
          "option": {
            "variableName": "userQuestion",
            "prompt": "请输入自己的发言",
            "defaultValue": " ",
            "inputMode": "singleLine"
          }
        }
      },
      {
        "name": "var03",
        "sourceType": "const",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": "0"
          }
        }
      },
      {
        "name": "var04",
        "sourceType": "const",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": "0"
          }
        }
      }
    ],
    "post_code": "def after_task(memory_bus,logger,process_control):\n    # 敏感词检测函数开始\n    def detectSensitiveWords(sentence):\n        sensitive_word_sentence_list = [\"腐败中国\",\"三个呆婊\",\"你办事我放心\",\"社会主义灭亡\",\"打倒中国\",\"共产党\",\"共产主义\",\"胡锦涛\",\"江泽民\",\"江主席\",\"李鹏\",\"罗干\",\"温家宝\",\"打倒中共\",\"习近平\",\"习主席\",\"朱镕基\",\"抵制中共\",\"灭亡中国\",\"亡党亡国\",\"粉碎四人帮\",\"激流中国\",\"特供\",\"特贡\",\"特共\",\"zf大楼\",\"殃视\",\"贪污腐败\",\"强制拆除\",\"形式主义\",\"政治风波\",\"太子党\",\"上海帮\",\"北京帮\",\"清华帮\",\"红色贵族\",\"权贵集团\",\"河蟹社会\",\"喝血社会\",\"九风\",\"9风\",\"十七大\",\"十7大\",\"17da\",\"九学\",\"9学\",\"四风\",\"4风\",\"双规\",\"南街村\",\"最淫官员\",\"警匪\",\"官匪\",\"独夫民贼\",\"官商勾结\",\"城管暴力执法\",\"强制捐款\",\"毒豺\",\"一党执政\",\"一党专制\",\"一党专政\",\"专制政权\",\"宪法法院\",\"胡平\",\"苏晓康\",\"贺卫方\",\"谭作人\",\"焦国标\",\"万润南\",\"张志新\",\"辛灝年\",\"高勤荣\",\"王炳章\",\"高智晟\",\"司马璐\",\"刘晓竹\",\"刘宾雁\",\"魏京生\",\"寻找林昭的灵魂\",\"别梦成灰\",\"谁是新中国\",\"讨伐中宣部\",\"异议人士\",\"民运人士\",\"启蒙派\",\"选国家主席\",\"民一主\",\"min主\",\"民竹\",\"民珠\",\"民猪\",\"chinesedemocracy\",\"大赦国际\",\"国际特赦\",\"da选\",\"投公\",\"公头\",\"宪政\",\"平反\",\"党章\",\"维权\",\"昝爱宗\",\"宪章\",\"08宪\",\"08xz\",\"抿主\",\"敏主\",\"人拳\",\"人木又\",\"人quan\",\"renquan\",\"中国人权\",\"中国新民党\",\"群体事件\",\"群体性事件\",\"上中央\",\"去中央\",\"讨说法\",\"请愿\",\"请命\",\"公开信\",\"联名上书\",\"万人大签名\",\"万人骚动\",\"截访\",\"上访\",\"shangfang\",\"信访\",\"访民\",\"集合\",\"集会\",\"组织集体\",\"静坐\",\"静zuo\",\"jing坐\",\"示威\",\"示wei\",\"游行\",\"you行\",\"油行\",\"游xing\",\"youxing\",\"官逼民反\",\"反party\",\"反共\",\"抗议\",\"亢议\",\"抵制\",\"低制\",\"底制\",\"di制\",\"抵zhi\",\"dizhi\",\"boycott\",\"血书\",\"焚烧中国国旗\",\"baoluan\",\"流血冲突\",\"出现暴动\",\"发生暴动\",\"引起暴动\",\"baodong\",\"灭共\",\"杀毙\",\"罢工\",\"霸工\",\"罢考\",\"罢餐\",\"霸餐\",\"罢参\",\"罢饭\",\"罢吃\",\"罢食\",\"罢课\",\"罢ke\",\"霸课\",\"ba课\",\"罢教\",\"罢学\",\"罢运\",\"网特\",\"网评员\",\"网络评论员\",\"五毛党\",\"五毛们\",\"5毛党\",\"戒严\",\"jieyan\",\"jie严\",\"戒yan\",\"8的平方事件\",\"知道64\",\"八九年\",\"贰拾年\",\"2o年\",\"20和谐年\",\"贰拾周年\",\"六四\",\"六河蟹四\",\"六百度四\",\"六和谐四\",\"陆四\",\"陆肆\",\"198964\",\"5月35\",\"89年春夏之交\",\"64惨案\",\"64时期\",\"64运动\",\"4事件\",\"四事件\",\"北京风波\",\"学潮\",\"学chao\",\"xuechao\",\"学百度潮\",\"门安天\",\"天按门\",\"坦克压大学生\",\"民主女神\",\"历史的伤口\",\"高自联\",\"北高联\",\"血洗京城\",\"四二六社论\",\"王丹\",\"柴玲\",\"沈彤\",\"封从德\",\"王超华\",\"王维林\",\"吾尔开希\",\"吾尔开西\",\"侯德健\",\"阎明复\",\"方励之\",\"蒋捷连\",\"丁子霖\",\"辛灏年\",\"蒋彦永\",\"严家其\",\"陈一咨\",\"中华局域网\",\"党的喉舌\",\"互联网审查\",\"当局严密封锁\",\"新闻封锁\",\"封锁消息\",\"爱国者同盟\",\"关闭所有论坛\",\"网络封锁\",\"金盾工程\",\"gfw\",\"无界浏览\",\"无界网络\",\"自由门\",\"何清涟\",\"中国的陷阱\",\"汪兆钧\",\"记者无疆界\",\"境外媒体\",\"维基百科\",\"纽约时报\",\"bbc中文网\",\"华盛顿邮报\",\"世界日报\",\"东森新闻网\",\"东森电视\",\"星岛日报\",\"wikipedia\",\"youtube\",\"googleblogger\",\"美国广播公司\",\"英国金融时报\",\"自由亚洲\",\"自由时报\",\"中国时报\",\"反分裂\",\"威胁论\",\"左翼联盟\",\"钓鱼岛\",\"保钓组织\",\"主权\",\"弓单\",\"火乍\",\"木仓\",\"石肖\",\"核蛋\",\"步qiang\",\"bao炸\",\"爆zha\",\"baozha\",\"zha药\",\"zha弹\",\"炸dan\",\"炸yao\",\"zhadan\",\"zhayao\",\"hmtd\",\"三硝基甲苯\",\"六氟化铀\",\"炸药配方\",\"弹药配方\",\"炸弹配方\",\"皮箱炸弹\",\"火药配方\",\"人体炸弹\",\"人肉炸弹\",\"解放军\",\"兵力部署\",\"军转\",\"军事社\",\"8341部队\",\"第21集团军\",\"七大军区\",\"7大军区\",\"北京军区\",\"沈阳军区\",\"济南军区\",\"成都军区\",\"广州军区\",\"南京军区\",\"兰州军区\",\"颜色革命\",\"规模冲突\",\"塔利班\",\"基地组织\",\"恐怖分子\",\"恐怖份子\",\"三股势力\",\"印尼屠华\",\"印尼事件\",\"蒋公纪念歌\",\"马英九\",\"mayingjiu\",\"李天羽\",\"苏贞昌\",\"林文漪\",\"陈水扁\",\"陈s扁\",\"陈随便\",\"阿扁\",\"a扁\",\"告全国同胞书\",\"台百度湾\",\"台完\",\"台wan\",\"taiwan\",\"台弯\",\"湾台\",\"台湾国\",\"台湾共和国\",\"台军\",\"台独\",\"台毒\",\"台du\",\"taidu\",\"twdl\",\"一中一台\",\"打台湾\",\"两岸战争\",\"攻占台湾\",\"支持台湾\",\"进攻台湾\",\"占领台湾\",\"统一台湾\",\"收复台湾\",\"登陆台湾\",\"解放台湾\",\"解放tw\",\"解决台湾\",\"光复民国\",\"台湾独立\",\"台湾问题\",\"台海问题\",\"台海危机\",\"台海统一\",\"台海大战\",\"台海战争\",\"台海局势\",\"入联\",\"入耳关\",\"中华联邦\",\"国民党\",\"x民党\",\"民进党\",\"青天白日\",\"闹独立\",\"duli\",\"fenlie\",\"日本万岁\",\"小泽一郎\",\"劣等民族\",\"汉人\",\"汉维\",\"维汉\",\"维吾\",\"吾尔\",\"热比娅\",\"伊力哈木\",\"疆独\",\"东突厥斯坦解放组织\",\"东突解放组织\",\"蒙古分裂分子\",\"列确\",\"阿旺晋美\",\"藏人\",\"臧人\",\"zang人\",\"藏民\",\"藏m\",\"达赖\",\"赖达\",\"dalai\",\"哒赖\",\"dl喇嘛\",\"丹增嘉措\",\"打砸抢\",\"西独\",\"藏独\",\"葬独\",\"臧独\",\"藏毒\",\"藏du\",\"zangdu\",\"支持zd\",\"藏暴乱\",\"藏青会\",\"雪山狮子旗\",\"拉萨\",\"啦萨\",\"啦沙\",\"啦撒\",\"拉sa\",\"lasa\",\"la萨\",\"西藏\",\"藏西\",\"藏春阁\",\"藏獨\",\"藏独\",\"藏独立\",\"藏妇会\",\"藏青会\",\"藏字石\",\"xizang\",\"xi藏\",\"x藏\",\"西z\",\"tibet\",\"希葬\",\"希藏\",\"硒藏\",\"稀藏\",\"西脏\",\"西奘\",\"西葬\",\"西臧\",\"援藏\",\"bjork\",\"王千源\",\"安拉\",\"回教\",\"回族\",\"回回\",\"回民\",\"穆斯林\",\"穆罕穆德\",\"穆罕默德\",\"默罕默德\",\"伊斯兰\",\"圣战组织\",\"清真\",\"清zhen\",\"qingzhen\",\"真主\",\"阿拉伯\",\"高丽棒子\",\"韩国狗\",\"满洲第三帝国\",\"满狗\",\"鞑子\",\"江丑闻\",\"江嫡系\",\"江毒\",\"江独裁\",\"江蛤蟆\",\"江核心\",\"江黑心\",\"江胡内斗\",\"江祸心\",\"江家帮\",\"江绵恒\",\"江派和胡派\",\"江派人马\",\"江泉集团\",\"江人马\",\"江三条腿\",\"江氏集团\",\"江氏家族\",\"江氏政治局\",\"江氏政治委员\",\"江梳头\",\"江太上\",\"江戏子\",\"江系人\",\"江系人马\",\"江宰民\",\"江贼\",\"江贼民\",\"麻果丸\",\"麻将透\",\"麻醉弹\",\"麻醉狗\",\"麻醉枪\",\"麻醉槍\",\"麻醉药\",\"麻醉藥\",\"台独\",\"台湾版假币\",\"台湾独立\",\"台湾国\",\"台湾应该独立\",\"台湾有权独立\",\"天灭中共\",\"中共帮凶\",\"中共保命\",\"中共裁\",\"中共党文化\",\"中共腐败\",\"中共的血旗\",\"中共的罪恶\",\"中共帝国\",\"中共独裁\",\"中共封锁\",\"中共封网\",\"中共腐败\",\"中共黑\",\"中共黑帮\",\"中共解体\",\"中共近期权力斗争\",\"中共恐惧\",\"中共权力斗争\",\"中共任用\",\"中共退党\",\"中共洗脑\",\"中共邪教\",\"中共政治游戏\",\"中共邪毒素\"]\n        # 遍历敏感词列表，检查是否在句子中\n        for word in sensitive_word_sentence_list:\n            if word in sentence:\n                return True\n        return False\n    # 敏感词检测函数结束    \n    choice = memory_bus.get(\"inputVar\")[\"isContinue\"]\n    if choice == \"1\":\n        studentView=memory_bus.get('inputVar')['userQuestion']\n        sensitive = detectSensitiveWords(studentView)\n        memory_bus.add(\"sensitive\",str(sensitive))\n        # result = [{\"type\":\"text\",\"data\":f\"你的输入：{studentView}\"}]\n        # logger.write(f\"你的输入：{studentView}\")\n        memory_bus.update(\"studentView\",studentView)\n        prompt1=f\"\"\"你是一个讨论课上一个学生的学伴，研讨的主题为“{memory_bus.get(\"topic\")}”。\n                该学生发言如下：\n                {studentView}\n                请根据研讨的主题，发表自己的看法。如果该学生没有提出看法，而是提出问题，不要直接回答他的问题。在回答问题的时候，可以偏离主题，也可以有明确的错误。\n                下面，请针对研讨主题“{memory_bus.get(\"topic\")}”，发表你的观点，你的回答应当以“我”开头。注意：你没有任何计算机的专业知识，在发表观点的时候，不要使用任何计算机的专业知识和背景信息。\"\"\"\n        prompt2=f\"\"\"你是一个讨论课上一个学生的学伴，研讨的主题为“{memory_bus.get(\"topic\")}”。\n                该学生发言如下：\n                {studentView}\n                请根据研讨的主题，发表自己的看法，总体水平和该学生相当或高于该学生，如果该学生没有提出看法，而是提出问题，不要直接回答他的问题。\n                下面，请针对研讨主题“{memory_bus.get(\"topic\")}”，发表你的观点，你的回答应当以“我”开头。\"\"\"\n        num = (memory_bus.get(\"assistant\") + 1) % 2\n        if num == 0:\n            prompt = prompt1\n            memory_bus.update(\"assistant\", 0)\n        else:\n            prompt = prompt2\n            memory_bus.update(\"assistant\", 1)\n        memory_bus.update(\"schoolmatePrompt\", prompt)\n        result = [{\"type\":\"text\",\"data\":f\"你的输入：{studentView}\"},{\"type\":\"text\",\"data\":\"学伴举手回答问题...\"}]\n    else:\n        # result = [{\"type\":\"text\",\"data\":\"用户选择退出本次研讨。\"},{\"type\":\"text\",\"data\":\"教师正在总结本次研讨...\"}]\n        logger.write(\"用户选择退出本次研讨\")\n        process_control.jump_process(9)\n    return result",
    "task": "学生提出针对上述主题的看法或者离开"
  },
  {
    "task_id": 5,
    "pre_code": "def before_task(memory_bus,logger,process_control):\n    sensitive = memory_bus.get(\"sensitive\")\n    if sensitive == \"True\":\n        process_control.abort_process()\n        return\n    else:\n        return",
    "tool_id": 10019,
    "parameters": [
      {
        "name": "content",
        "sourceType": "refer",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": "codeVar.schoolmatePrompt"
          }
        }
      }
    ],
    "post_code": "def after_task(memory_bus,logger,process_control):\n    memory_bus.get(\"dialog\").append({\"role\": \"student\",\"value\": memory_bus.get(\"studentView\")})\n    llmRepy = memory_bus.get(\"thisTask\")[\"choices\"][0][\"message\"][\"content\"]\n    memory_bus.get(\"dialog\").append({\"role\": \"schoolmate\",\"value\": llmRepy})\n    diaglog=str(memory_bus.get(\"dialog\"))\n    from markdown import markdown\n    llmRepy = markdown(llmRepy, extensions=['nl2br'])\n    prestr = \"学伴的回答是：\"\n    if memory_bus.get(\"assistant\") == 0:\n        prestr = \"<strong>日常滑水的小强</strong>的发言如下：\" \n    else:\n        prestr = \"<strong>积极上进的小红</strong>的发言如下：\"\n    result = [{\"type\":\"text\",\"data\":prestr+llmRepy}]\n    return result",
    "task": "随机选一个学伴档次"
  },
  {
    "task_id": 6,
    "pre_code": "def before_task(memory_bus,logger,process_control):\n    return",
    "tool_id": 1,
    "parameters": [],
    "post_code": "def after_task(memory_bus,logger,process_control):\n    import re\n    def check_text_for_keywords(text):\n        \"\"\"\n        检查输入文本是否包含指定的关键词，以此判断文本是否可能包含问题\n        :param text: 待检查的文本内容\n        :return: 如果包含关键词返回 True，否则返回 False\n        \"\"\"\n        # 定义关键词列表\n        keywords = [\n            \"什么\", \"为什么\", \"如何\", \"多少\", \"几\", \"谁\", \"哪里\", \"何处\",\n            \"是否\", \"啥\",\"咋办\", \"？\", \"?\"\n        ]\n        # 构建正则表达式模式\n        pattern = re.compile(\"|\".join(map(re.escape, keywords)))\n        return bool(pattern.search(text))\n    text = memory_bus.get(\"dialog\")[-2][\"value\"] + memory_bus.get(\"dialog\")[-1][\"value\"]\n    logger.write(str(text))\n    result = check_text_for_keywords(text)\n    logger.write(str(result))\n    prompt = f\"\"\"回答以下内容中的问题{text}。注意在回答中不要使用有序列表，且仅输入回答的内容。\"\"\"\n    if result:\n        memory_bus.update(\"assistantPrompt\",prompt)\n    else:\n        process_control.jump_process(4)\n    return [{\"type\":\"text\",\"data\":\"助教举手发言...\"}]",
    "task": "正则匹配是否包含问题"
  },
  {
    "task_id": 7,
    "pre_code": "def before_task(memory_bus,logger,process_control):\n    return",
    "tool_id": 10019,
    "parameters": [
      {
        "name": "content",
        "sourceType": "refer",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": "codeVar.assistantPrompt"
          }
        }
      }
    ],
    "post_code": "def after_task(memory_bus,logger,process_control):\n    llmRepy = memory_bus.get(\"thisTask\")[\"choices\"][0][\"message\"][\"content\"]\n    memory_bus.get(\"dialog\").append({\"role\": \"assistant\",\"value\": llmRepy})\n    from markdown import markdown\n    llmRepy = markdown(llmRepy, extensions=['nl2br'])\n    result = [{\"type\":\"text\",\"data\":\"助教的回答是：\"+llmRepy}]\n    return result",
    "task": "助教回答问题"
  },
  {
    "task_id": 8,
    "pre_code": "def before_task(memory_bus,logger,process_control):\n    process_control.jump_process(4)\n    return",
    "tool_id": 1,
    "parameters": [],
    "post_code": "def after_task(memory_bus,logger,process_control):\n    return",
    "task": "跳转到学生发言"
  },
  {
    "task_id": 9,
    "pre_code": "def before_task(memory_bus,logger,process_control):\n    return",
    "tool_id": 1,
    "parameters": [],
    "post_code": "def after_task(memory_bus,logger,process_control):\n    prompt = f\"\"\"你是一名教师，你组织了一次主题为“{memory_bus.get(\"topic\")}”的讨论课，现在请根据以下对话给出其中对于role是student的那一个学生发言进行点评：{str(memory_bus.get(\"dialog\"))}。注意直接点评就好，不要输出多余的内容。\"\"\"\n    memory_bus.add(\"summarizePrompt\",prompt)\n    result = [{\"type\":\"text\",\"data\":\"教师正在总结本次研讨...\"}]\n    return result",
    "task": "构造教师点评提示词"
  },
  {
    "task_id": 10,
    "pre_code": "def before_task(memory_bus,logger,process_control):\n    return",
    "tool_id": 10019,
    "parameters": [
      {
        "name": "content",
        "sourceType": "refer",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": "codeVar.summarizePrompt"
          }
        }
      }
    ],
    "post_code": "def after_task(memory_bus,logger,process_control):\n    llmRepy = memory_bus.get(\"thisTask\")[\"choices\"][0][\"message\"][\"content\"]\n    from markdown import markdown\n    llmRepy = markdown(llmRepy, extensions=['nl2br'])\n    result = [{\"type\":\"text\",\"data\":\"教师对学生发言的总结：\" + llmRepy}]\n    return result",
    "task": "教师点评"
  },
  {
    "task_id": 11,
    "pre_code": "def before_task(memory_bus,logger,process_control):\n    return",
    "tool_id": 41,
    "parameters": [
      {
        "name": "var01",
        "sourceType": "input",
        "sourceData": {
          "type": "editBox",
          "option": {
            "variableName": "lastStudentView",
            "prompt": "请讲解本次研讨相关的知识点",
            "defaultValue": "",
            "inputMode": "multiLine"
          }
        }
      },
      {
        "name": "var02",
        "sourceType": "const",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": ""
          }
        }
      },
      {
        "name": "var03",
        "sourceType": "const",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": ""
          }
        }
      },
      {
        "name": "var04",
        "sourceType": "const",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": ""
          }
        }
      }
    ],
    "post_code": "def after_task(memory_bus,logger,process_control):\n    lastStudentView = memory_bus.get(\"inputVar\")['lastStudentView']\n    prompt = f\"\"\"你是一名教师，你组织了一次主题为“{memory_bus.get(\"topic\")}”的讨论课，现在学生经过讨论后进行了自己的讲解。请你对学生的讲解进行点评，并给出0-5的评分。学生的讲解如下：{lastStudentView}。注意：必须明确给出对学生的评分。如下是示例：\n学生的评分为：2\n具体说明如下：\n...\n    \"\"\"\n    memory_bus.add(\"lastQa\",prompt)\n    result = [{\"type\":\"text\",\"data\":\"教师正在评价学生的讲解...\"}]\n    return result",
    "task": "学生讲解研讨的知识点"
  },
  {
    "task_id": 12,
    "pre_code": "def before_task(memory_bus,logger,process_control):\n    return",
    "tool_id": 10019,
    "parameters": [
      {
        "name": "content",
        "sourceType": "refer",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": "codeVar.lastQa"
          }
        }
      }
    ],
    "post_code": "def after_task(memory_bus,logger,process_control):\n    llmRepy = memory_bus.get(\"thisTask\")[\"choices\"][0][\"message\"][\"content\"]\n    from markdown import markdown\n    llmRepy = markdown(llmRepy, extensions=['nl2br'])\n    result = [{\"type\":\"text\",\"data\":\"教师对学生讲解的评价：\" + llmRepy}]\n    return result",
    "task": "对学生最后的讲解评分"
  },
  {
    "task_id": 13,
    "pre_code": "def before_task(memory_bus,logger,process_control):\n    return",
    "tool_id": 41,
    "parameters": [
      {
        "name": "var01",
        "sourceType": "input",
        "sourceData": {
          "type": "singleSelect",
          "option": {
            "variableName": "isSubmit",
            "prompt": "是否将此次研讨提交给老师",
            "options": [
              {
                "name": "将本次研讨提交给老师",
                "value": "0",
                "checked": "true"
              },
              {
                "name": "放弃提交本次研讨",
                "value": "1",
                "checked": "false"
              }
            ]
          }
        }
      },
      {
        "name": "var02",
        "sourceType": "const",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": "1"
          }
        }
      },
      {
        "name": "var03",
        "sourceType": "const",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": "2"
          }
        }
      },
      {
        "name": "var04",
        "sourceType": "const",
        "sourceData": {
          "type": "default",
          "option": {
            "defaultValue": "3"
          }
        }
      }
    ],
    "post_code": "def after_task(memory_bus,logger,process_control):\n    choice = memory_bus.get(\"inputVar\")[\"isSubmit\"]\n    if choice == \"0\":\n        return [{\"type\":\"text\",\"data\":\"已将本次研讨提交给老师！\"}]\n    return",
    "task": "学生是否提交本次会话"
  }
]