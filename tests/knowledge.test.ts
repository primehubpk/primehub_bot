import test from "node:test";
import assert from "node:assert/strict";
import {knowledgeAnswer,needsHuman,wantsResellerSignup} from "../lib/knowledge";

test("Prime Skill answer is short and useful",()=>{const r=knowledgeAnswer("Prime Skill kya hai?","");assert.ok(r?.text.includes("Prime Skill"));assert.ok(r?.link);});
test("reseller signup intent is detected",()=>{assert.equal(wantsResellerSignup("reseller pe signup kar do"),true);});
test("payment confusion triggers NEED YOU",()=>{assert.equal(needsHuman("samajh nahi aya payment"),true);});
test("admin notes can answer latest feature",()=>{const r=knowledgeAnswer("what's new?","New wholesale feature live hai.");assert.ok(r?.text.includes("New wholesale"));});
